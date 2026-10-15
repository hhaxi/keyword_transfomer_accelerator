// Autonomous fixed-shape DMA engine. Only shared data SRAM is addressable.
// One registered master request plus one in-flight response; retire/refill may
// happen on the same edge. An offered command is never withdrawn on abort.
module kwt_dma(
    input wire clk,rst_n,
    input wire cmd_valid, output wire cmd_ready, input wire [19:0] cmd_addr,
    input wire cmd_read, input wire [31:0] cmd_wdata, input wire [3:0] cmd_wmask,
    output reg rsp_valid, input wire rsp_ready, output reg [31:0] rsp_rdata,
    output reg rsp_err,
    output wire m_valid, input wire m_ready, output reg [31:0] m_addr,m_wdata,
    output reg m_read, output wire [3:0] m_mask,
    input wire m_rsp_valid, output wire m_rsp_ready, input wire [31:0] m_rdata,
    input wire m_err
);
    localparam IDLE=3'd0, CLEAR=3'd1, LOAD=3'd2, LAUNCH=3'd3, RUN=3'd4, DRAIN=3'd5;
    reg [2:0] phase;
    reg [31:0] xbase,wbase,bbase,ybase;
    reg done,error,aborted,config_error;
    reg req_valid,outstanding,outstanding_read;
    reg [15:0] read_scheduled,read_received,write_scheduled,write_received;
    reg [63:0] output_hold;
    reg output_have,output_high;
    reg [31:0] total_cycles,load_cycles,run_cycles,other_cycles;
    reg [31:0] request_wait,response_wait,read_commands,write_commands;
    reg [31:0] first_output,last_output,last_write,producer_wait;
    reg first_seen;
    wire active=phase!=IDLE;
    wire take=cmd_valid && cmd_ready;
    wire wr=take && !cmd_read && cmd_addr[1:0]==0 && cmd_wmask==4'hf;
    wire abort_now=wr && cmd_addr==0 && cmd_wdata==2;
    wire start_request=wr && cmd_addr==0 && cmd_wdata==1;
    // Keep code, stack and mailbox outside all DMA ranges. Bounds are checked
    // using subtraction from the fixed end, so 32-bit address wrap is rejected.
    wire addresses_ok=xbase[1:0]==0 && wbase[1:0]==0 && bbase[1:0]==0 && ybase[1:0]==0 &&
        xbase>=32'ha0010000 && xbase<=32'ha0080000-32'd12672 &&
        wbase>=32'ha0010000 && wbase<=32'ha0080000-32'd32768 &&
        bbase>=32'ha0010000 && bbase<=32'ha0080000-32'd1024 &&
        ybase>=32'ha0010000 && ybase<=32'ha0080000-32'd202752 &&
        (ybase+32'd202752<=xbase || xbase+32'd12672<=ybase) &&
        (ybase+32'd202752<=wbase || wbase+32'd32768<=ybase) &&
        (ybase+32'd202752<=bbase || bbase+32'd1024<=ybase);
    wire start=start_request && !active && addresses_ok;
    wire core_load_ready,core_valid,core_done,core_fault;
    wire unused_cmd_ready,unused_rsp_valid,unused_rsp_err;
    wire [31:0] unused_rsp_data;
    wire [63:0] core_data;
    wire [31:0] core_cycles,mac_cycles,fifo_wait;
    wire bus_error=m_rsp_valid && m_err;
    wire engine_fault=core_fault || (phase==LOAD && !core_load_ready);
    wire stopping=abort_now || bus_error || (engine_fault && active) || phase==DRAIN;
    wire core_clear=phase==CLEAR || (phase==DRAIN && !req_valid && !outstanding) || (abort_now && !active);
    wire core_take=phase==RUN && !output_have && !stopping;
    wire core_load=phase==LOAD && m_rsp_valid && !stopping;
    // Core addresses refer to the first element of each packed pair. Bias is
    // still a full signed 32-bit word; output representation is unchanged.
    wire [19:0] load_addr=read_received<3168 ? 20'h10000+{1'b0,read_received,3'b0} :
        (read_received<11360 ? 20'h20000+(({4'b0,read_received}-20'd3168)<<3) :
                              20'h30000+(({4'b0,read_received}-20'd11360)<<2));
    assign cmd_ready=!rsp_valid || rsp_ready;
    assign m_valid=req_valid;
    assign m_mask=4'hf;
    // LOAD follows a synchronous core clear, so its SRAM writer always accepts
    // one word per clock. Never couple response-ready to a CPU abort handshake.
    assign m_rsp_ready=1'b1;
    wire accept=req_valid && m_ready;
    wire retire=m_rsp_valid && m_rsp_ready;
    wire refill=(!req_valid || m_ready) && !stopping;
    wire schedule_read=refill && phase==LOAD && read_scheduled<11616;
    wire schedule_write=refill && phase==RUN && output_have;

    kwt_accel core(.clk(clk),.rst_n(rst_n),.cmd_valid(1'b0),.cmd_ready(unused_cmd_ready),.cmd_addr(20'b0),
        .cmd_read(1'b0),.cmd_wdata(32'b0),.cmd_wmask(4'b0),.rsp_valid(unused_rsp_valid),
        .rsp_ready(1'b1),.rsp_rdata(unused_rsp_data),.rsp_err(unused_rsp_err),
        .dma_mode(1'b1),.dma_load_valid(core_load),.dma_load_addr(load_addr),.dma_load_data(m_rdata),
        .dma_load_ready(core_load_ready),.dma_start(phase==LAUNCH && !stopping),.dma_clear(core_clear),
        .dma_out_valid(core_valid),.dma_out_data(core_data),.dma_out_ready(core_take),
        .dma_done(core_done),.dma_fault(core_fault),.perf_cycles(core_cycles),
        .perf_mac_cycles(mac_cycles),.perf_fifo_wait(fifo_wait));

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            phase<=IDLE; xbase<=0;wbase<=0;bbase<=0;ybase<=0;
            done<=0;error<=0;aborted<=0;config_error<=0;
            req_valid<=0;outstanding<=0;outstanding_read<=0;m_addr<=0;m_wdata<=0;m_read<=1;
            read_scheduled<=0;read_received<=0;write_scheduled<=0;write_received<=0;
            output_hold<=0;output_have<=0;output_high<=0;
            total_cycles<=0;load_cycles<=0;run_cycles<=0;other_cycles<=0;
            request_wait<=0;response_wait<=0;read_commands<=0;write_commands<=0;
            first_output<=0;last_output<=0;last_write<=0;producer_wait<=0;first_seen<=0;
            rsp_valid<=0;rsp_rdata<=0;rsp_err<=0;
        end else begin
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            if(active) begin
                total_cycles<=total_cycles+1;
                if(phase==LOAD) load_cycles<=load_cycles+1;
                else if(phase==RUN) run_cycles<=run_cycles+1;
                else other_cycles<=other_cycles+1;
                if(req_valid && !m_ready) request_wait<=request_wait+1;
                if(m_rsp_valid && !m_rsp_ready) response_wait<=response_wait+1;
                if(phase==RUN && !output_have && !core_valid && write_scheduled<50688)
                    producer_wait<=producer_wait+1;
            end
            case({accept,retire})
                2'b10: outstanding<=1;
                2'b01: outstanding<=0;
                default: begin end
            endcase
            if(accept) begin
                outstanding_read<=m_read;
                if(m_read) read_commands<=read_commands+1;
                else write_commands<=write_commands+1;
            end
            if(accept) req_valid<=0;
            if(schedule_read) begin
                req_valid<=1;m_read<=1;m_wdata<=0;
                if(read_scheduled<3168) m_addr<=xbase+({16'b0,read_scheduled}<<2);
                else if(read_scheduled<11360) m_addr<=wbase+(({16'b0,read_scheduled}-3168)<<2);
                else m_addr<=bbase+(({16'b0,read_scheduled}-11360)<<2);
                read_scheduled<=read_scheduled+1'b1;
            end
            if(schedule_write) begin
                req_valid<=1;m_read<=0;m_addr<=ybase+({16'b0,write_scheduled}<<2);
                m_wdata<=output_high ? output_hold[63:32] : output_hold[31:0];
                write_scheduled<=write_scheduled+1'b1;
                output_high<=!output_high;
                if(output_high) output_have<=0;
            end
            if(core_valid && core_take) begin
                output_hold<=core_data;output_have<=1;output_high<=0;
                if(!first_seen) begin first_seen<=1;first_output<=total_cycles+1;end
                last_output<=total_cycles+1;
            end
            if(phase==CLEAR) phase<=LOAD;
            if(phase==LAUNCH) phase<=RUN;
            if(retire && !stopping) begin
                if(phase==LOAD && outstanding_read) begin
                    read_received<=read_received+1'b1;
                    if(read_received==11615) phase<=LAUNCH;
                end
                if(phase==RUN && !outstanding_read) begin
                    write_received<=write_received+1'b1;
                    if(write_received==50687) begin
                        // Completion is the final SRAM write response, not MAC done.
                        last_write<=total_cycles+1;phase<=IDLE;done<=1;
                        if(!core_done) begin error<=1;done<=0;phase<=DRAIN;end
                    end
                end
            end
            if(phase==DRAIN && !req_valid && !outstanding) begin
                phase<=IDLE;output_have<=0;output_high<=0;
            end
            if(active && (bus_error || engine_fault)) begin phase<=DRAIN;error<=1;done<=0;end
            if(abort_now) begin
                done<=0;config_error<=0;
                if(active) begin phase<=DRAIN;aborted<=1;end
                else begin error<=0;aborted<=0;end
            end
            if(start) begin
                phase<=CLEAR;done<=0;error<=0;aborted<=0;config_error<=0;
                read_scheduled<=0;read_received<=0;write_scheduled<=0;write_received<=0;
                output_have<=0;output_high<=0;
                total_cycles<=0;load_cycles<=0;run_cycles<=0;other_cycles<=0;
                request_wait<=0;response_wait<=0;read_commands<=0;write_commands<=0;
                first_output<=0;last_output<=0;last_write<=0;producer_wait<=0;first_seen<=0;
            end
            if(take) begin
                rsp_valid<=1;rsp_rdata<=0;rsp_err<=0;
                if(cmd_read && cmd_addr[1:0]==0) begin
                    case(cmd_addr)
                        20'h04: rsp_rdata<={27'b0,config_error,aborted,error,done,active};
                        20'h0c: rsp_rdata<=32'h4b575434;
                        20'h20: rsp_rdata<=xbase;
                        20'h24: rsp_rdata<=wbase;
                        20'h28: rsp_rdata<=bbase;
                        20'h2c: rsp_rdata<=ybase;
                        20'h40: rsp_rdata<=total_cycles;
                        20'h44: rsp_rdata<=load_cycles;
                        20'h48: rsp_rdata<=run_cycles;
                        20'h4c: rsp_rdata<=other_cycles;
                        20'h50: rsp_rdata<=mac_cycles;
                        20'h54: rsp_rdata<=fifo_wait;
                        20'h58: rsp_rdata<=core_cycles;
                        20'h5c: rsp_rdata<=request_wait;
                        20'h60: rsp_rdata<=response_wait;
                        20'h64: rsp_rdata<=read_commands;
                        20'h68: rsp_rdata<=write_commands;
                        20'h6c: rsp_rdata<=first_output;
                        20'h70: rsp_rdata<=last_output;
                        20'h74: rsp_rdata<=last_write;
                        20'h78: rsp_rdata<=producer_wait;
                        default: begin rsp_err<=1;config_error<=1;end
                    endcase
                end else if(wr && !active && cmd_addr>=20'h20 && cmd_addr<=20'h2c) begin
                    case(cmd_addr)
                        20'h20: xbase<=cmd_wdata;
                        20'h24: wbase<=cmd_wdata;
                        20'h28: bbase<=cmd_wdata;
                        20'h2c: ybase<=cmd_wdata;
                        default: begin end
                    endcase
                end else if(!(start || abort_now)) begin rsp_err<=1;config_error<=1;end
            end
        end
    end
endmodule
