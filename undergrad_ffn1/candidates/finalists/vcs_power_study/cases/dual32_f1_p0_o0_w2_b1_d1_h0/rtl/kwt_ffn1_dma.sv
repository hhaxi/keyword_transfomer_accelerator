// Lossless optional DMA: tiled input reservation, indexed INT64/packed40 writes.
// Two in-order credits, one registered offer, final write-response completion.
`include "kwt_options.vh"
`include "kwt_optional.vh"
module kwt_ffn1_dma(
    input wire clk,rst_n,
    input wire cmd_valid,output wire cmd_ready,input wire [19:0] cmd_addr,
    input wire cmd_read,input wire [31:0] cmd_wdata,input wire [3:0] cmd_wmask,
    output reg rsp_valid,input wire rsp_ready,output reg [31:0] rsp_rdata,output reg rsp_err,
    output wire m_valid,input wire m_ready,output reg [31:0] m_addr,m_wdata,
    output reg m_read,output wire [3:0] m_mask,
    input wire m_rsp_valid,output wire m_rsp_ready,input wire [31:0] m_rdata,input wire m_err,output wire irq_event
);
    localparam IDLE=0,CLEAR=1,LOAD=2,LAUNCH=3,RUN=4,DRAIN=5;
    reg [2:0] phase;
    reg [31:0] xbase,wbase,bbase,ybase;
    reg done,error,aborted,config_error,req_valid;
    reg old_done,old_error,old_config_error;
    assign irq_event=(done && !old_done) || (error && !old_error) || (config_error && !old_config_error);
    always @(posedge clk or negedge rst_n)
        if(!rst_n) begin old_done<=0;old_error<=0;old_config_error<=0;end
        else begin old_done<=done;old_error<=error;old_config_error<=config_error;end
    reg [1:0] outstanding_count;
    reg response_head,response_tail;reg response_read[0:1];
    reg [19:0] response_target[0:1],request_target;
    reg [1:0] row_reserved,row_loaded;
    reg [6:0] reserved_row[0:1];
    wire [1:0] core_x_free;
    wire outstanding=outstanding_count!=0;
    wire outstanding_read=response_read[response_head];
    reg [15:0] read_scheduled,read_received,write_scheduled,write_received;
    localparam OUTPUT_WORDS=`KWT_OUTPUT_WORDS;
    localparam OUTPUT_BYTES=OUTPUT_WORDS*4;
    localparam TILE_SHIFT=`KWT_TILE_ROWS==4 ? 2 : (`KWT_TILE_ROWS==2 ? 1 : 0);
    reg [14:0] flat_output_index;
    wire formatted_valid,formatted_empty,formatted_fault;
    wire [31:0] formatted_data;wire [15:0] formatted_index;
    wire formatter_ready;
    reg [31:0] total_cycles,load_cycles,run_cycles,other_cycles;
    reg [31:0] request_wait,response_wait,read_commands,write_commands;
    reg [31:0] first_output,last_output,last_write,producer_wait;reg first_seen;
    wire active=phase!=IDLE;
    wire take=cmd_valid && cmd_ready;
    wire wr=take && !cmd_read && cmd_addr[1:0]==0 && cmd_wmask==15;
    wire abort_now=wr && cmd_addr==0 && cmd_wdata==2;
    wire start_request=wr && cmd_addr==0 && cmd_wdata==1;
    wire addresses_ok=xbase[1:0]==0 && wbase[1:0]==0 && bbase[1:0]==0 && ybase[1:0]==0 &&
        xbase>=32'ha0010000 && xbase<=32'ha0080000-12672 &&
        wbase>=32'ha0010000 && wbase<=32'ha0080000-32768 &&
        bbase>=32'ha0010000 && bbase<=32'ha0080000-1024 &&
        ybase>=32'ha0010000 && ybase<=32'ha0080000-OUTPUT_BYTES &&
        (ybase+OUTPUT_BYTES<=xbase || xbase+12672<=ybase) &&
        (ybase+OUTPUT_BYTES<=wbase || wbase+32768<=ybase) &&
        (ybase+OUTPUT_BYTES<=bbase || bbase+1024<=ybase);
    wire start=start_request && !active && addresses_ok;
    wire core_load_ready,core_valid,core_done,core_fault;
    wire [63:0] core_data;wire [14:0] core_index;wire [31:0] core_cycles,mac_cycles,fifo_wait;
    wire load_response=(phase==LOAD || phase==LAUNCH || phase==RUN) && m_rsp_valid && outstanding_read;
    wire bus_error=m_rsp_valid && m_err;
    wire engine_fault=core_fault || formatted_fault || (load_response && !core_load_ready);
    wire stopping=abort_now || bus_error || (engine_fault && active) || phase==DRAIN;
    wire core_clear=phase==CLEAR || (phase==DRAIN && !req_valid && !outstanding) || (abort_now && !active);
    wire accept=req_valid && m_ready;
    wire retire=m_rsp_valid && m_rsp_ready;
    wire [2:0] credits_next={1'b0,outstanding_count}+{2'b0,accept}-{2'b0,retire};
    wire refill=(!req_valid || m_ready) && !stopping && credits_next<2;
    wire [15:0] x_scheduled=read_scheduled-16'd8448;
    wire [6:0] candidate_row=x_scheduled[11:5];
    wire [6:0] candidate_tile=candidate_row>>TILE_SHIFT;
    wire candidate_bank=candidate_tile[0];
    wire x_slot_available=core_x_free[candidate_bank] &&
        (!row_reserved[candidate_bank] || reserved_row[candidate_bank]==candidate_tile);
    wire schedule_read=refill && (phase==CLEAR || phase==LOAD || phase==LAUNCH || phase==RUN) && read_scheduled<11616 &&
        (!`KWT_SMALL_X || read_scheduled<8448 || x_slot_available);
    wire schedule_write=refill && phase==RUN && formatted_valid && !schedule_read;
    wire core_take=phase==RUN && !stopping && formatter_ready;
    wire [19:0] legacy_load_addr=read_received<3168 ? 20'h10000+{1'b0,read_received,3'b0} :
        (read_received<11360 ? 20'h20000+(({4'b0,read_received}-3168)<<3) :
                              20'h30000+(({4'b0,read_received}-11360)<<2));
    wire [19:0] load_addr=`KWT_SMALL_X ? response_target[response_head] : legacy_load_addr;
    assign cmd_ready=!rsp_valid || rsp_ready;
    assign m_valid=req_valid;assign m_mask=15;assign m_rsp_ready=1'b1;
    generate if(`KWT_USE_TILE) begin: tile_engine
        kwt_tile_core #(.ROWS(`KWT_TILE_ROWS),.COLS(`KWT_TILE_COLS),.KPAR(`KWT_TILE_KPAR),
            .FUSE(`KWT_FUSE),.PRODUCT_PIPE(`KWT_PRODUCT_PIPE),.SMALL_BIAS(`KWT_SMALL_BIAS)) core(
            .clk(clk),.rst_n(rst_n),.dma_load_valid(load_response && !stopping),
            .dma_load_addr(load_addr),.dma_load_data(m_rdata),.dma_load_ready(core_load_ready),
            .dma_start(phase==LAUNCH && !stopping),.dma_clear(core_clear),.dma_x_free(core_x_free),
            .dma_out_valid(core_valid),.dma_out_data(core_data),.dma_out_index(core_index),.dma_out_ready(core_take),
            .dma_done(core_done),.dma_fault(core_fault),.perf_cycles(core_cycles),
            .perf_mac_cycles(mac_cycles),.perf_fifo_wait(fifo_wait));
    end else begin: original_engine
        kwt_ffn1_core core(.clk(clk),.rst_n(rst_n),.dma_load_valid(load_response && !stopping),
            .dma_load_addr(load_addr),.dma_load_data(m_rdata),.dma_load_ready(core_load_ready),
            .dma_start(phase==LAUNCH && !stopping),.dma_clear(core_clear),.dma_x_free(core_x_free),
            .dma_out_valid(core_valid),.dma_out_data(core_data),.dma_out_ready(core_take),
            .dma_done(core_done),.dma_fault(core_fault),.perf_cycles(core_cycles),
            .perf_mac_cycles(mac_cycles),.perf_fifo_wait(fifo_wait));
        assign core_index=flat_output_index;
    end endgenerate
    kwt_output_formatter #(.PACKED40(`KWT_PACKED40)) formatter(.clk(clk),.rst_n(rst_n),.clear(core_clear),
        .in_valid(core_valid && phase==RUN && !stopping),.in_ready(formatter_ready),
        .in_data(core_data[39:0]),.in_index(core_index),
        .out_valid(formatted_valid),.out_ready(schedule_write),.out_data(formatted_data),.out_index(formatted_index),
        .empty(formatted_empty),.fault(formatted_fault));
    always @(posedge clk or negedge rst_n)
        if(!rst_n) flat_output_index<=0;
        else if(core_clear) flat_output_index<=0;
        else if(core_valid && core_take) flat_output_index<=flat_output_index+1'b1;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            phase<=IDLE;xbase<=0;wbase<=0;bbase<=0;ybase<=0;
            done<=0;error<=0;aborted<=0;config_error<=0;req_valid<=0;
            outstanding_count<=0;response_head<=0;response_tail<=0;
            row_reserved<=0;row_loaded<=0;reserved_row[0]<=0;reserved_row[1]<=0;request_target<=0;
            m_addr<=0;m_wdata<=0;m_read<=1;read_scheduled<=0;read_received<=0;
            write_scheduled<=0;write_received<=0;
            total_cycles<=0;load_cycles<=0;run_cycles<=0;other_cycles<=0;
            request_wait<=0;response_wait<=0;read_commands<=0;write_commands<=0;
            first_output<=0;last_output<=0;last_write<=0;producer_wait<=0;first_seen<=0;
            rsp_valid<=0;rsp_rdata<=0;rsp_err<=0;
        end else begin
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            if(`KWT_SMALL_X) begin
                if(row_loaded[0] && core_x_free[0]) begin row_reserved[0]<=0;row_loaded[0]<=0;end
                if(row_loaded[1] && core_x_free[1]) begin row_reserved[1]<=0;row_loaded[1]<=0;end
            end
            if(active) begin
                total_cycles<=total_cycles+1;
                if(phase==LOAD) load_cycles<=load_cycles+1;
                else if(phase==RUN) run_cycles<=run_cycles+1;
                else other_cycles<=other_cycles+1;
                if(req_valid && !m_ready) request_wait<=request_wait+1;
                if(m_rsp_valid && !m_rsp_ready) response_wait<=response_wait+1;
                if(phase==RUN && !formatted_valid && !core_valid && write_scheduled<OUTPUT_WORDS) producer_wait<=producer_wait+1;
            end
            outstanding_count<=credits_next[1:0];
            if(retire) response_head<=!response_head;
            if(accept) begin
                response_read[response_tail]<=m_read;response_tail<=!response_tail;
                response_target[response_tail]<=request_target;
                if(m_read) read_commands<=read_commands+1;else write_commands<=write_commands+1;
                req_valid<=0;
            end
            if(schedule_read) begin
                req_valid<=1;m_read<=1;m_wdata<=0;
                if(`KWT_SMALL_X) begin
                    if(read_scheduled<8192) begin
                        m_addr<=wbase+({16'b0,read_scheduled}<<2);
                        request_target<=20'h20000+({4'b0,read_scheduled}<<3);
                    end else if(read_scheduled<8448) begin
                        m_addr<=bbase+(({16'b0,read_scheduled}-8192)<<2);
                        request_target<=20'h30000+(({4'b0,read_scheduled}-8192)<<2);
                    end else begin
                        m_addr<=xbase+({16'b0,x_scheduled}<<2);
                        request_target<=20'h10000+({4'b0,x_scheduled}<<3);
                        row_reserved[candidate_bank]<=1;
                        reserved_row[candidate_bank]<=candidate_tile;
                    end
                end else begin
                    if(read_scheduled<3168) m_addr<=xbase+({16'b0,read_scheduled}<<2);
                    else if(read_scheduled<11360) m_addr<=wbase+(({16'b0,read_scheduled}-3168)<<2);
                    else m_addr<=bbase+(({16'b0,read_scheduled}-11360)<<2);
                end
                read_scheduled<=read_scheduled+1'b1;
            end
            if(schedule_write) begin
                req_valid<=1;m_read<=0;m_addr<=ybase+({16'b0,formatted_index}<<2);
                m_wdata<=formatted_data;
                write_scheduled<=write_scheduled+1'b1;
            end
            if(core_valid && core_take) begin
                if(!first_seen) begin first_seen<=1;first_output<=total_cycles+1;end
                last_output<=total_cycles+1;
            end
            if(phase==CLEAR) phase<=LOAD;
            if(phase==LAUNCH) phase<=RUN;
            if(retire && !stopping) begin
                if(load_response) begin
                    read_received<=read_received+1'b1;
                    if(read_received==(`KWT_SMALL_X ? (8448+32*`KWT_TILE_ROWS-1) : 11615)) phase<=LAUNCH;
                    if(`KWT_SMALL_X && load_addr[19:16]==1 && load_addr[7:3]==31 && ((load_addr[14:8] & (`KWT_TILE_ROWS-1))==(`KWT_TILE_ROWS-1) || load_addr[14:8]==98)) row_loaded[(load_addr[14:8]>>TILE_SHIFT)&1]<=1;
                end
                if(phase==RUN && !outstanding_read) begin
                    write_received<=write_received+1'b1;
                    if(write_received==OUTPUT_WORDS-1) begin
                        last_write<=total_cycles+1;phase<=IDLE;done<=1;
                        if(!core_done || !formatted_empty) begin error<=1;done<=0;phase<=DRAIN;end
                    end
                end
            end
            if(phase==DRAIN && !req_valid && !outstanding) begin phase<=IDLE;end
            if(active && (bus_error || engine_fault)) begin phase<=DRAIN;error<=1;done<=0;end
            if(abort_now) begin
                done<=0;config_error<=0;
                if(active) begin phase<=DRAIN;aborted<=1;end else begin error<=0;aborted<=0;end
            end
            if(start) begin
                phase<=CLEAR;done<=0;error<=0;aborted<=0;config_error<=0;
                row_reserved<=0;row_loaded<=0;
                read_scheduled<=0;read_received<=0;write_scheduled<=0;write_received<=0;
                total_cycles<=0;load_cycles<=0;run_cycles<=0;other_cycles<=0;
                request_wait<=0;response_wait<=0;read_commands<=0;write_commands<=0;
                first_output<=0;last_output<=0;last_write<=0;producer_wait<=0;first_seen<=0;
            end
            if(take) begin
                rsp_valid<=1;rsp_rdata<=0;rsp_err<=0;
                if(cmd_read && cmd_addr[1:0]==0) begin
                    case(cmd_addr)
                        20'h04:rsp_rdata<={27'b0,config_error,aborted,error,done,active};
                        20'h0c:rsp_rdata<=32'h4b575435;
                        20'h20:rsp_rdata<=xbase;20'h24:rsp_rdata<=wbase;20'h28:rsp_rdata<=bbase;20'h2c:rsp_rdata<=ybase;
                        20'h38:rsp_rdata<=`KWT_PACKED40;
                        20'h40:rsp_rdata<=total_cycles;20'h44:rsp_rdata<=load_cycles;20'h48:rsp_rdata<=run_cycles;
                        20'h4c:rsp_rdata<=other_cycles;20'h50:rsp_rdata<=mac_cycles;20'h54:rsp_rdata<=fifo_wait;
                        20'h58:rsp_rdata<=core_cycles;20'h5c:rsp_rdata<=request_wait;20'h60:rsp_rdata<=response_wait;
                        20'h64:rsp_rdata<=read_commands;20'h68:rsp_rdata<=write_commands;
                        20'h6c:rsp_rdata<=first_output;20'h70:rsp_rdata<=last_output;20'h74:rsp_rdata<=last_write;20'h78:rsp_rdata<=producer_wait;
                        default:begin rsp_err<=1;config_error<=1;end
                    endcase
                end else if(wr && !active && cmd_addr>=20'h20 && cmd_addr<=20'h2c) begin
                    case(cmd_addr)
                        20'h20:xbase<=cmd_wdata;20'h24:wbase<=cmd_wdata;20'h28:bbase<=cmd_wdata;20'h2c:ybase<=cmd_wdata;
                        default:begin end
                    endcase
                end else if(wr && !active && cmd_addr==20'h38 && cmd_wdata==`KWT_PACKED40) begin end
                else if(!(start || abort_now)) begin rsp_err<=1;config_error<=1;end
            end
        end
    end
endmodule
