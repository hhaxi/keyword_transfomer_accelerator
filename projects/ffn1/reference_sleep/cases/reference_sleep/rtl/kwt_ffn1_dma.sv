// Tiled input reservation and indexed writes of paired INT16 results.
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
    localparam IDLE=0,CLEAR=1,LOAD=2,LAUNCH=3,RUN=4,DRAIN=5,X_CLEAR=6;
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
    reg [13:0] weight_scheduled,x_scheduled;
    reg [8:0] bias_scheduled,bias_received,x_tile_word;
    reg [3:0] x_tile_scheduled;
    reg weight_complete,decoder_x_mode;
    function [3:0] ordered_tile;
        input [3:0] sequence_number;
        begin ordered_tile=`KWT_TAIL_FIRST ? (sequence_number==0 ? 4'd12 : ((sequence_number-1'b1)^4'd1)) : sequence_number;end
    endfunction
    localparam X_BYTES_MAX=`KWT_X_DELTA ? 13424 : 12672;
    localparam OUTPUT_WORDS=`KWT_OUTPUT_WORDS;
    localparam OUTPUT_BYTES=OUTPUT_WORDS*4;
    localparam TILE_SHIFT=$clog2(`KWT_TILE_ROWS);
    reg [14:0] flat_output_index;
    wire formatted_valid,formatted_empty;
    wire [31:0] formatted_data;wire [15:0] formatted_index;
    reg [31:0] total_cycles,load_cycles,run_cycles,other_cycles;
    reg [31:0] request_wait,response_wait,read_commands,write_commands;
    reg [31:0] first_output,last_output,last_write,producer_wait;reg first_seen;
    wire active=phase!=IDLE;
    wire take=cmd_valid && cmd_ready;
    wire wr=take && !cmd_read && cmd_addr[1:0]==0 && cmd_wmask==15;
    wire abort_now=wr && cmd_addr==0 && cmd_wdata==2;
    wire start_request=wr && cmd_addr==0 && cmd_wdata==1;
    wire addresses_ok=xbase[1:0]==0 && wbase[1:0]==0 && bbase[1:0]==0 && ybase[1:0]==0 &&
        xbase>=32'ha0010000 && xbase<=32'ha0080000-X_BYTES_MAX &&
        wbase>=32'ha0010000 && wbase<=32'ha0080000-32896 &&
        bbase>=32'ha0010000 && bbase<=32'ha0080000-1024 &&
        ybase>=32'ha0010000 && ybase<=32'ha0080000-OUTPUT_BYTES &&
        (ybase+OUTPUT_BYTES<=xbase || xbase+X_BYTES_MAX<=ybase) &&
        (ybase+OUTPUT_BYTES<=wbase || wbase+32896<=ybase) &&
        (ybase+OUTPUT_BYTES<=bbase || bbase+1024<=ybase);
    wire start=start_request && !active && addresses_ok;
    wire core_load_ready,core_valid,core_done,core_fault;
    wire [63:0] core_data;wire [14:0] core_index;wire [31:0] core_cycles,mac_cycles,fifo_wait;
    wire decoder_ready,decoder_valid,decoder_metadata,decoder_done,decoder_fault;
    wire core_w_ready,core_x_ready;
    wire [67:0] decoder_residual;
    wire [8:0] decoder_tile_words;
    wire [63:0] decoder_quad;
    wire [11:0] decoder_index;
    wire [13:0] decoder_words;
    wire response_phase=phase==LOAD || phase==LAUNCH || phase==RUN;
    wire weight_response=outstanding && outstanding_read && response_target[response_head][19:16]==4;
    wire x_response=outstanding && outstanding_read && response_target[response_head][19:16]==1;
    wire decoder_response=weight_response || (`KWT_X_DELTA && x_response);
    wire load_response=response_phase && m_rsp_valid && outstanding && outstanding_read && !decoder_response;
    wire bus_error=m_rsp_valid && outstanding && m_err;
    wire engine_fault=core_fault || decoder_fault || (load_response && !core_load_ready);
    wire stopping=abort_now || bus_error || (engine_fault && active) || phase==DRAIN;
    wire core_clear=phase==CLEAR || (phase==DRAIN && !req_valid && !outstanding) || (abort_now && !active);
    wire accept=req_valid && m_ready;
    wire retire=m_rsp_valid && m_rsp_ready;
    wire [2:0] credits_next={1'b0,outstanding_count}+{2'b0,accept}-{2'b0,retire};
    wire refill=(!req_valid || m_ready) && !stopping && credits_next<2;
    wire [3:0] candidate_tile=ordered_tile(x_tile_scheduled);
    wire candidate_bank=candidate_tile[0];
    wire [11:0] candidate_x_word={candidate_tile,8'b0}+{3'b0,x_tile_word};
    wire [8:0] candidate_words=`KWT_X_DELTA ? decoder_tile_words : (candidate_tile==12 ? 9'd96 : 9'd256);
    wire x_slot_available=core_x_free[candidate_bank] &&
        (!row_reserved[candidate_bank] || reserved_row[candidate_bank]=={3'b0,candidate_tile});
    wire schedule_weight=refill && !weight_complete && !decoder_x_mode && (phase==CLEAR || phase==LOAD) &&
        weight_scheduled<(decoder_metadata ? decoder_words : 14'd32);
    wire schedule_bias=refill && weight_complete && response_phase && bias_scheduled<256;
    wire x_header_pending=`KWT_X_DELTA && x_scheduled<16;
    wire x_payload_available=x_tile_scheduled<13 && x_slot_available &&
        (!`KWT_X_DELTA || decoder_metadata);
    wire schedule_x=refill && weight_complete && response_phase && bias_scheduled==256 &&
        (x_header_pending || x_payload_available);
    wire schedule_read=schedule_bias || schedule_x;
    wire schedule_write=refill && phase==RUN && formatted_valid && !schedule_read && !schedule_weight;
    wire core_take=schedule_write;
    wire [19:0] load_addr=response_target[response_head];
    wire [31:0] load_data=m_rdata;
    wire local_load_valid=load_response && retire && !stopping;
    assign cmd_ready=!rsp_valid || rsp_ready;
    assign m_valid=req_valid;assign m_mask=15;
    // An abort/error always drains pending responses, including when unpacking
    // was stalled. Normal compressed responses obey the decoder input credit.
    assign m_rsp_ready=(phase==DRAIN) || !decoder_response || decoder_ready;
    kwt_weight_unpack #(.TAIL_FIRST(`KWT_TAIL_FIRST)) weight_unpack(.clk(clk),.rst_n(rst_n),
        .clear(phase==CLEAR || phase==X_CLEAR || (phase==DRAIN && !req_valid && !outstanding)),
        .x_mode(decoder_x_mode),.x_query_tile(candidate_tile),.x_query_words(decoder_tile_words),
        .in_valid(response_phase && m_rsp_valid && decoder_response && !stopping),
        .in_ready(decoder_ready),.in_word(m_rdata),.out_valid(decoder_valid),
        .out_ready((decoder_x_mode ? core_x_ready : core_w_ready) && active && !stopping),
        .out_quad(decoder_quad),.out_residual(decoder_residual),.out_index(decoder_index),
        .metadata_valid(decoder_metadata),.expected_words(decoder_words),.done(decoder_done),.fault(decoder_fault));
    generate if(`KWT_USE_TILE) begin: tile_engine
        kwt_tile_core #(.ROWS(`KWT_TILE_ROWS),.COLS(`KWT_TILE_COLS),.KPAR(`KWT_TILE_KPAR),
            .FUSE(`KWT_FUSE),.PRODUCT_PIPE(`KWT_PRODUCT_PIPE),.SMALL_BIAS(`KWT_SMALL_BIAS),
            .X_DELTA(`KWT_X_DELTA),.TAIL_FIRST(`KWT_TAIL_FIRST)) core(
            .clk(clk),.rst_n(rst_n),.dma_load_valid(local_load_valid),
            .dma_load_addr(load_addr),.dma_load_data(load_data),.dma_load_ready(core_load_ready),
            .dma_w_valid(decoder_valid && !decoder_x_mode && active && !stopping),.dma_w_ready(core_w_ready),
            .dma_w_quad(decoder_quad),.dma_w_index(decoder_index),
            .dma_x_valid(decoder_valid && decoder_x_mode && active && !stopping),.dma_x_ready(core_x_ready),
            .dma_x_residual(decoder_residual),.dma_x_index(decoder_index[10:0]),
            .dma_start(phase==LAUNCH && !stopping),.dma_clear(core_clear),.dma_x_free(core_x_free),
            .dma_out_valid(core_valid),.dma_out_data(core_data),.dma_out_index(core_index),.dma_out_ready(core_take),
            .dma_done(core_done),.dma_fault(core_fault),.perf_cycles(core_cycles),
            .perf_mac_cycles(mac_cycles),.perf_fifo_wait(fifo_wait));
    end else begin: original_engine
        kwt_ffn1_core core(.clk(clk),.rst_n(rst_n),.dma_load_valid(local_load_valid),
            .dma_load_addr(load_addr),.dma_load_data(load_data),.dma_load_ready(core_load_ready),
            .dma_start(phase==LAUNCH && !stopping),.dma_clear(core_clear),.dma_x_free(core_x_free),
            .dma_out_valid(core_valid),.dma_out_data(core_data),.dma_out_ready(core_take),
            .dma_done(core_done),.dma_fault(core_fault),.perf_cycles(core_cycles),
            .perf_mac_cycles(mac_cycles),.perf_fifo_wait(fifo_wait));
        assign core_w_ready=1'b0;assign core_x_ready=1'b0;
        assign core_index=flat_output_index;
    end endgenerate
    assign formatted_valid=core_valid;
    assign formatted_data=core_data[31:0];
    assign formatted_index={1'b0,core_index};
    assign formatted_empty=!core_valid;
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
            m_addr<=0;m_wdata<=0;m_read<=1;read_scheduled<=0;read_received<=0;weight_scheduled<=0;
            x_scheduled<=0;bias_scheduled<=0;bias_received<=0;x_tile_word<=0;x_tile_scheduled<=0;weight_complete<=0;decoder_x_mode<=0;
            write_scheduled<=0;write_received<=0;
            total_cycles<=0;load_cycles<=0;run_cycles<=0;other_cycles<=0;
            request_wait<=0;response_wait<=0;read_commands<=0;write_commands<=0;
            first_output<=0;last_output<=0;last_write<=0;producer_wait<=0;first_seen<=0;
            rsp_valid<=0;rsp_rdata<=0;rsp_err<=0;
        end else begin
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            if(`KWT_SMALL_X) begin
                if(row_reserved[0] && !core_x_free[0]) row_loaded[0]<=1;
                if(row_reserved[1] && !core_x_free[1]) row_loaded[1]<=1;
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
            if(schedule_weight) begin
                req_valid<=1;m_read<=1;m_wdata<=0;
                m_addr<=wbase+({18'b0,weight_scheduled}<<2);
                request_target<=20'h40000;
                weight_scheduled<=weight_scheduled+1'b1;
            end
            if(schedule_bias) begin
                req_valid<=1;m_read<=1;m_wdata<=0;
                m_addr<=bbase+({23'b0,bias_scheduled}<<2);
                request_target<=20'h30000+({11'b0,bias_scheduled}<<2);
                bias_scheduled<=bias_scheduled+1'b1;
                read_scheduled<=read_scheduled+1'b1;
            end
            if(schedule_x) begin
                req_valid<=1;m_read<=1;m_wdata<=0;
                if(`KWT_X_DELTA) begin
                    m_addr<=xbase+({18'b0,x_scheduled}<<2);request_target<=20'h10000;
                end else begin
                    m_addr<=xbase+({20'b0,candidate_x_word}<<2);
                    request_target<=20'h10000+({8'b0,candidate_x_word}<<3);
                end
                x_scheduled<=x_scheduled+1'b1;
                read_scheduled<=read_scheduled+1'b1;
                if(!x_header_pending) begin
                    row_reserved[candidate_bank]<=1;reserved_row[candidate_bank]<={3'b0,candidate_tile};
                    if(x_tile_word==candidate_words-1'b1) begin x_tile_word<=0;x_tile_scheduled<=x_tile_scheduled+1'b1;end
                    else x_tile_word<=x_tile_word+1'b1;
                end
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
            if(phase==CLEAR || phase==X_CLEAR) phase<=LOAD;
            if(phase==LOAD && !weight_complete && decoder_done && !stopping) begin
                weight_complete<=1;
                if(`KWT_X_DELTA) begin decoder_x_mode<=1;phase<=X_CLEAR;end
            end
            if(phase==LOAD && weight_complete && bias_received==256 && !core_x_free[0] && !stopping) phase<=LAUNCH;
            if(phase==LAUNCH) phase<=RUN;
            if(retire && !stopping) begin
                if(outstanding_read && !weight_response) begin
                    read_received<=read_received+1'b1;
                    if(!x_response) bias_received<=bias_received+1'b1;
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
                read_scheduled<=0;read_received<=0;weight_scheduled<=0;
            x_scheduled<=0;bias_scheduled<=0;bias_received<=0;x_tile_word<=0;x_tile_scheduled<=0;weight_complete<=0;decoder_x_mode<=0;write_scheduled<=0;write_received<=0;
                total_cycles<=0;load_cycles<=0;run_cycles<=0;other_cycles<=0;
                request_wait<=0;response_wait<=0;read_commands<=0;write_commands<=0;
                first_output<=0;last_output<=0;last_write<=0;producer_wait<=0;first_seen<=0;
            end
            if(take) begin
                rsp_valid<=1;rsp_rdata<=0;rsp_err<=0;
                if(cmd_read && cmd_addr[1:0]==0) begin
                    case(cmd_addr)
                        20'h04:rsp_rdata<={27'b0,config_error,aborted,error,done,active};
                        20'h0c:rsp_rdata<=32'h4b575438;
                        20'h20:rsp_rdata<=xbase;20'h24:rsp_rdata<=wbase;20'h28:rsp_rdata<=bbase;20'h2c:rsp_rdata<=ybase;
                        20'h38:rsp_rdata<=`KWT_OUTPUT_FORMAT;
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
                end else if(wr && !active && cmd_addr==20'h38 && cmd_wdata==`KWT_OUTPUT_FORMAT) begin end
                else if(!(start || abort_now)) begin rsp_err<=1;config_error<=1;end
            end
        end
    end
endmodule
