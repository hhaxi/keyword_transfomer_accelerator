// Row scheduling around the existing FFN1, GELU and FFN2 modules.
// Six lanes handle 16 rows each. The seventh pads its three rows to the
// eight-row FFN2 tile size and commits only the three real rows.
module kwt_ffn_rows_parallel #(parameter STREAM=0, parameter GELU_CYCLES=1)(
    input wire clk, rst_n,
    input wire cmd_valid, output wire cmd_ready, input wire [11:0] cmd_addr,
    input wire cmd_read, input wire [31:0] cmd_wdata, input wire [3:0] cmd_wmask,
    output reg rsp_valid, input wire rsp_ready, output reg [31:0] rsp_rdata, output reg rsp_err,
    output reg m_valid, input wire m_ready, output reg [31:0] m_addr, m_wdata, output reg m_read,
    input wire m_rsp_valid, input wire [31:0] m_rdata, input wire m_err,
    input wire preload_permit,
    input wire input_valid, output wire input_ready, input wire [31:0] input_data,
    output reg result_valid, input wire result_ready, output wire [39:0] result_data,
    output wire link_error
);
    localparam IDLE=0, CLEAR=1, W1=2, B1=3, W2=4, B2=5, LOAD_X=6,
        LAUNCH=7, COMPUTE=8, FETCH_Y=9, STORE_Y=10, DRAIN=11;
    reg [3:0] state;
    reg [12:0] index;
    reg [31:0] cycles;
    reg [4:0] shift_in, shift_out;
    reg pending, high_word, done, fault, aborted;
    wire busy=state!=IDLE;
    wire accept=cmd_valid && cmd_ready;
    wire write=accept && !cmd_read && cmd_wmask==15 && cmd_addr[1:0]==0;
    wire abort_request=write && cmd_addr==0 && cmd_wdata==2;
    wire bus_idle=!pending && !m_valid;
    wire retire=pending && m_rsp_valid;
    wire receive=retire && !m_err && !abort_request;
    wire direct_input=STREAM!=0 && state==LOAD_X;
    assign input_ready=direct_input && !abort_request;
    wire input_fire=input_valid && input_ready;
    assign link_error=STREAM!=0 && (fault || aborted);
    wire [31:0] read_base=state==W1 ? 32'ha0020000 : state==B1 ? 32'ha0028000 :
        state==W2 ? 32'ha0040000 : state==B2 ? 32'ha0048000 : 32'ha0018000;
    wire [12:0] read_last=(state==W1 || state==W2) ? 13'd8191 :
        state==B1 ? 13'd255 : state==B2 ? 13'd63 : 13'd3167;
    wire [6:0] lanes_done, lanes_fault;
    wire [63:0] lane_output[0:6];
    wire [31:0] first_lane_cycles;
    wire [2:0] output_lane=index[12:10];
    wire [63:0] output_value=lane_output[output_lane];
    reg [12:0] stream_index;
    reg [2:0] stream_lane;
    wire stream_fetch=STREAM!=0 && done && stream_index<6336 && (!result_valid || result_ready);
    assign result_data=lane_output[stream_lane][39:0];
    assign cmd_ready=!rsp_valid || rsp_ready;

    genvar lane;
    generate for(lane=0;lane<7;lane=lane+1) begin: rows
        wire [31:0] lane_cycles;
        if(lane==0) assign first_lane_cycles=lane_cycles;
        kwt_ffn_row_lane #(.ROWS(lane==6 ? 3 : 16),.GELU_CYCLES(GELU_CYCLES)) engine(
            .clk(clk),.rst_n(rst_n),.clear(state==CLEAR || (state==DRAIN && bus_idle)),
            .launch(state==LAUNCH),.done(lanes_done[lane]),.fault(lanes_fault[lane]),.cycles(lane_cycles),
            .load_w1(receive && state==W1),.load_b1(receive && state==B1),
            .load_w2(receive && state==W2),.load_b2(receive && state==B2),
            .load_x((direct_input ? input_fire : receive && state==LOAD_X) && index[11:9]==lane),
            .load_index(index),.load_data(direct_input ? input_data : m_rdata),.shift_in(shift_in),.shift_out(shift_out),
            .fetch(STREAM!=0 ? stream_fetch && stream_index[12:10]==lane : state==FETCH_Y && output_lane==lane),
            .fetch_index(STREAM!=0 ? stream_index[9:0] : index[9:0]),.output_data(lane_output[lane])
        );
    end endgenerate

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;index<=0;cycles<=0;shift_in<=0;shift_out<=0;
            pending<=0;high_word<=0;done<=0;fault<=0;aborted<=0;
            m_valid<=0;m_addr<=0;m_wdata<=0;m_read<=0;
            rsp_valid<=0;rsp_rdata<=0;rsp_err<=0;
            stream_index<=0;stream_lane<=0;result_valid<=0;
        end else begin
            if(busy) cycles<=cycles+1'b1;
            if(m_valid && m_ready) begin m_valid<=0;pending<=1;end
            if(retire) pending<=0;
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            if(result_ready) result_valid<=0;
            if(stream_fetch) begin
                result_valid<=1;
                stream_lane<=stream_index[12:10];
                stream_index<=stream_index+1'b1;
            end
            case(state)
                CLEAR:begin index<=0;high_word<=0;state<=W1;end
                W1,B1,W2,B2,LOAD_X:begin
                    if(!direct_input && bus_idle && !abort_request && (STREAM==0 || preload_permit)) begin
                        m_valid<=1;m_read<=1;m_addr<=read_base+{17'd0,index,2'b0};
                    end
                    if(receive || input_fire) begin
                        if(index==read_last) begin index<=0;state<=state+1'b1;end
                        else index<=index+1'b1;
                    end
                end
                LAUNCH:state<=COMPUTE;
                COMPUTE:if(&lanes_done) begin
                    if(STREAM!=0) begin state<=IDLE;done<=1;end
                    else state<=FETCH_Y;
                end
                FETCH_Y:state<=STORE_Y;
                STORE_Y:begin
                    if(bus_idle && !abort_request) begin
                        m_valid<=1;m_read<=0;m_addr<=32'ha0030000+{16'd0,index,high_word,2'b0};
                        m_wdata<=high_word ? output_value[63:32] : output_value[31:0];
                    end
                    if(receive) begin
                        high_word<=!high_word;
                        if(high_word) begin
                            if(index==6335) begin state<=IDLE;done<=1;end
                            else begin index<=index+1'b1;state<=FETCH_Y;end
                        end
                    end
                end
                DRAIN:if(bus_idle) state<=IDLE;
                default:begin end
            endcase
            if(accept) begin
                rsp_valid<=1;rsp_rdata<=0;rsp_err<=0;
                if(cmd_addr[1:0]!=0) rsp_err<=1;
                else if(cmd_read) case(cmd_addr)
                    12'h004:rsp_rdata<={28'd0,aborted,fault,done,busy};
                    12'h00c:rsp_rdata<=32'h46464e5a;
                    12'h040:rsp_rdata<=cycles;
                    12'h044:rsp_rdata<=first_lane_cycles;
                    default:rsp_err<=1;
                endcase
                else if(cmd_wmask!=15) rsp_err<=1;
                else case(cmd_addr)
                    12'h000:if(cmd_wdata==1 && !busy) begin
                        state<=CLEAR;done<=0;fault<=0;aborted<=0;cycles<=0;
                        stream_index<=0;result_valid<=0;
                    end else if(cmd_wdata!=2) rsp_err<=1;
                    12'h03c:if(!busy && (cmd_wdata&32'hffffe0e0)==0) begin
                        shift_in<=cmd_wdata[4:0];shift_out<=cmd_wdata[12:8];
                    end else rsp_err<=1;
                    default:rsp_err<=1;
                endcase
            end
            if(busy && state!=DRAIN &&
               (abort_request || (state!=CLEAR && ((retire && m_err) || |lanes_fault)))) begin
                state<=DRAIN;done<=0;fault<=!abort_request;aborted<=abort_request;
            end
            if(STREAM!=0 && abort_request && !busy) begin done<=0;result_valid<=0;end
        end
    end
endmodule

module kwt_ffn_row_lane #(parameter ROWS=16, parameter GELU_CYCLES=1)(
    input wire clk, rst_n, clear, launch,
    output wire done, fault, output wire [31:0] cycles,
    input wire load_w1, load_b1, load_w2, load_b2, load_x,
    input wire [12:0] load_index, input wire [31:0] load_data,
    input wire [4:0] shift_in, shift_out,
    input wire fetch, input wire [9:0] fetch_index,
    output wire [63:0] output_data
);
    localparam IDLE=0, FIRST_ROW=1, START=2, RUN=3, DONE=4;
    localparam [9:0] REAL_WORDS=ROWS*32, TILE_WORDS=((ROWS+7)/8)*256;
    localparam [10:0] REAL_OUTPUTS=ROWS*64;
    reg [2:0] state;
    reg [9:0] input_index;
    reg [10:0] output_index;
    reg input_pending;
    wire [31:0] input_word, input_q;
    wire [63:0] output_q;
    wire [1:0] free_banks;
    wire l1_ready,l1_valid,l1_fault,l2_ready,l2_valid;
    wire [63:0] l1_output,l2_output;
    reg [39:0] gelu_input;
    wire gelu_accept, gelu_valid;
    if(GELU_CYCLES==1) begin: single_cycle
        reg valid;
        assign gelu_accept=state==RUN && (!valid || l2_ready);
        assign gelu_valid=valid;
        always @(posedge clk) begin
            if(!rst_n || clear) valid<=0;
            else if(gelu_accept) valid<=l1_valid;
        end
    end else begin: held_gelu
        // The input stays fixed for two edges before FFN2 can store GELU.
        reg [1:0] age;
        assign gelu_accept=state==RUN && (age==0 || (gelu_valid && l2_ready));
        assign gelu_valid=age==2;
        always @(posedge clk) begin
            if(!rst_n || clear) age<=0;
            else if(gelu_accept) age<=l1_valid ? 2'd1 : 2'd0;
            else if(age==1) age<=2;
        end
    end
    wire feeding=state==FIRST_ROW || state==RUN;
    wire fetch_input=feeding && !input_pending && input_index<TILE_WORDS && free_banks[input_index[5]];
    wire feed_input=feeding && input_pending;
    wire pop_output=state==RUN && l2_valid;
    wire [19:0] address=load_w1 ? 20'h20000+{4'd0,load_index,3'd0} :
        load_b1 ? 20'h30000+{5'd0,load_index,2'd0} : 20'h10000+{7'd0,input_index,3'd0};
    assign done=state==DONE;
    assign fault=l1_fault;

    localparam IN_AW=$clog2(REAL_WORDS), OUT_AW=$clog2(REAL_OUTPUTS);
    assign input_word=input_index<REAL_WORDS ? input_q : 32'd0;
    assign output_data=output_q;
    for(genvar half=0;half<2;half=half+1) begin: input_memory
        kwt_sram16 #(.AW(IN_AW)) memory(.clk(clk),
            .cs(load_x || (fetch_input && input_index<REAL_WORDS)),.we(load_x),
            .addr(load_x ? load_index[IN_AW-1:0] : input_index[IN_AW-1:0]),
            .din(load_data[half*16+:16]),.dout(input_q[half*16+:16]));
    end
    for(genvar half=0;half<4;half=half+1) begin: output_memory
        kwt_sram16 #(.AW(OUT_AW)) memory(.clk(clk),.cs(pop_output || fetch),.we(pop_output),
            .addr(pop_output ? output_index[OUT_AW-1:0] : fetch_index[OUT_AW-1:0]),
            .din(l2_output[half*16+:16]),.dout(output_q[half*16+:16]));
    end
`ifndef SYNTHESIS
    always @(posedge clk) if(rst_n) begin
        if(load_x && fetch_input) $fatal(1,"FFN input SRAM port collision");
        if(pop_output && fetch) $fatal(1,"FFN output SRAM port collision");
    end
`endif

    kwt_ffn1_core ffn1(
        .clk(clk),.rst_n(rst_n),.dma_load_valid(load_w1 || load_b1 || feed_input),
        .dma_load_addr(address),.dma_load_data(feed_input ? input_word : load_data),.dma_load_ready(l1_ready),
        .dma_start(state==START),.dma_clear(clear),.dma_x_free(free_banks),
        .dma_out_valid(l1_valid),.dma_out_data(l1_output),.dma_out_ready(gelu_accept),
        .dma_done(),.dma_fault(l1_fault),.perf_cycles(cycles),.perf_mac_cycles(),.perf_fifo_wait()
    );
    kwt_ffn2_stream ffn2(
        .clk(clk),.rst_n(rst_n),.clear(clear),
        .weight_write(load_w2),.weight_index(load_index),.weight_data(load_data),
        .bias_write(load_b2),.bias_index(load_index[5:0]),.bias_data(load_data),
        .gelu_input_shift(shift_in),.gelu_output_shift(shift_out),
        .input_valid(gelu_valid && state==RUN),.input_ready(l2_ready),.input_data(gelu_input),
        .output_valid(l2_valid),.output_ready(state==RUN),.output_data(l2_output)
    );

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;input_index<=0;output_index<=0;input_pending<=0;
        end else if(clear) begin
            state<=IDLE;input_index<=0;output_index<=0;input_pending<=0;
        end
        else begin
            if(gelu_accept && l1_valid) gelu_input<=l1_output[39:0];
            if(launch) state<=FIRST_ROW;
            if(fetch_input) input_pending<=1;
            if(feed_input && l1_ready) begin
                input_pending<=0;input_index<=input_index+1'b1;
                if(state==FIRST_ROW && input_index==31) state<=START;
            end
            if(state==START) state<=RUN;
            if(pop_output) begin
                output_index<=output_index+1'b1;
                if(output_index==REAL_OUTPUTS-1'b1) state<=DONE;
            end
        end
    end
endmodule
