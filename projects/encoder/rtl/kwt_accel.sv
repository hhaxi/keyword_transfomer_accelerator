// One outstanding 32-bit ICB transaction. Offsets are relative to 0x40000000.
// Legacy MMIO: one int16 per word. DMA: two adjacent int16 per word,
// with an element-index address (8-byte stride). W remains column-major.
module kwt_accel(
    input wire clk, rst_n,
    input wire cmd_valid, output wire cmd_ready,
    input wire [19:0] cmd_addr, input wire cmd_read,
    input wire [31:0] cmd_wdata, input wire [3:0] cmd_wmask,
    output reg rsp_valid, input wire rsp_ready,
    output reg [31:0] rsp_rdata, output reg rsp_err,
    // Dedicated DMA streaming interface; legacy MMIO is disabled in this mode.
    input wire dma_mode, dma_load_valid, input wire [19:0] dma_load_addr,
    input wire [31:0] dma_load_data, output wire dma_load_ready,
    input wire dma_start, dma_clear, input wire ffn_mode, dma_input_stream,
    input wire [4:0] gelu_input_shift,gelu_output_shift,
    output wire dma_out_valid,
    output wire [63:0] dma_out_data, input wire dma_out_ready,
    output wire dma_done, dma_fault,
    output wire [31:0] perf_cycles, perf_mac_cycles, perf_fifo_wait,
    output reg [31:0] perf_second_mac,perf_gelu,perf_saturation,perf_gelu_overlap,perf_parameter_wait
);
    localparam IDLE=4'd0, BREQ=4'd1, BLOAD=4'd2, PRIME=4'd3,
               MAC=4'd4, LAST=4'd5, EMIT=4'd6, DRAIN=4'd7, GELU=4'd8, MERGE=4'd9, WAIT_X=4'd10;
    reg [3:0] state;
    // A/B switch: output groups can merge directly into the existing FIFO.
    // GELU still receives a separately registered merge, exactly as before.
`ifdef KWT_BASELINE_OUTPUT_MERGE
    localparam OUTPUT_MERGE_FUSED=0;
`else
    localparam OUTPUT_MERGE_FUSED=1;
`endif
    reg second_stage;
    reg [2:0] gelu_lane,gelu_row;
    reg [4:0] gelu_group;
    reg gelu_busy;
    wire merge_fire=state==MERGE && !gelu_busy;
    wire full_ffn=dma_mode && ffn_mode;
    // Both modes use all sixteen existing MACs: even/odd k partial sums.
    wire [7:0] k_step=8'd2;
    wire mac_enable=state==MAC || state==LAST;
    wire signed [39:0] odd_acc [0:7];
    reg signed [39:0] merged [0:7];
    reg [14:0] nw2;
    reg [6:0] nb2;
    reg [6:0] row;
    reg [7:0] col;
    reg [7:0] k;
    reg [2:0] bias_lane, bias_return_lane;
    reg [31:0] next_bias [0:7];
    // Two groups decouple eight output lanes (sixteen MACs) from transfers.
    // Payload is unreset; reset/abort invalidate every entry via count/pointers.
    reg [39:0] fifo [0:15];
    reg [3:0] head, tail;
    reg [4:0] count;
    reg [14:0] outputs_read;
    reg [12:0] nx;
    reg [14:0] nw;
    reg [8:0] nb;
    reg done, fault;
    reg [31:0] cycles;
    reg [31:0] mac_cycles, fifo_wait;
    wire busy = state != IDLE;
    wire take = cmd_valid && cmd_ready;
    wire aligned = cmd_addr[1:0] == 0;
    wire [19:0] load_addr = dma_mode ? dma_load_addr : cmd_addr;
    wire [31:0] load_data = dma_mode ? dma_load_data : cmd_wdata;
    wire xsel = load_addr >= 20'h10000 && load_addr < 20'h16300;
    wire wsel = load_addr >= 20'h20000 && load_addr < 20'h30000;
    wire bsel = load_addr >= 20'h30000 && load_addr < 20'h30400;
    wire load = dma_mode ? (dma_load_valid && dma_load_ready) :
                (take && !cmd_read && aligned && cmd_wmask == 4'hf && !busy);
    wire xwrite = load && xsel && load_addr[1:0]==0 && (!dma_mode || !load_addr[2]) && load_addr[14:2] == nx && nx < 6336;
    wire wwrite = load && wsel && load_addr[1:0]==0 && (!dma_mode || !load_addr[2]) && load_addr[15:2] == nw[13:0] && nw < 16384;
    wire bwrite = load && bsel && load_addr[1:0]==0 && load_addr[9:2] == nb[7:0] && nb < 256;
    wire w2sel=load_addr>=20'h40000 && load_addr<20'h50000;
    wire b2sel=load_addr>=20'h50000 && load_addr<20'h50100;
    wire w2write=load && full_ffn && w2sel && load_addr[2:0]==0 && load_addr[15:2]==nw2[13:0] && nw2<16384;
    wire b2write=load && full_ffn && b2sel && load_addr[1:0]==0 && load_addr[7:2]==nb2[5:0] && nb2<64;
    wire complete_load = (dma_input_stream ? nx>=512 : nx==6336) && nw == 16384 && nb == 256;
    wire second_ready=nw2==16384 && nb2==64;
    wire start = !busy && complete_load && (dma_mode ? dma_start :
                 (load && cmd_addr == 0 && cmd_wdata == 1));
    wire clear = dma_mode ? dma_clear :
                 (take && !cmd_read && cmd_addr == 0 && cmd_wmask == 4'hf && cmd_wdata == 2);
    wire pop = count != 0 && (dma_mode ? dma_out_ready :
               (take && cmd_read && cmd_addr == 20'h14));
    wire push = state == EMIT && count <= 8;
    // Prime the next group on the edge that retires the current group.
    // MERGE still captures the old accumulators before their nonblocking init;
    // L2 primes only on FIFO acceptance, so backpressure cannot lose operands.
    wire tile_end = row[2:0]==7 || row==98;
    wire group_last = col==(second_stage ? 8'd56 : 8'd248);
    wire prime_next = !(group_last && (full_ffn ? tile_end : row==98)) &&
        (full_ffn && !second_stage ? merge_fire : push);
    wire [6:0] operand_row = prime_next && group_last ? row+7'd1 : row;
    wire [4:0] operand_group = prime_next ? (group_last ? 5'd0 : col[7:3]+5'd1) : col[7:3];
    wire [7:0] operand_k = prime_next ? 8'd0 : k;
    wire read_operands = state == PRIME || state == MAC || prime_next;
    wire mac_init = state==PRIME || prime_next;
    wire [12:0] xa = xwrite ? load_addr[14:2] : {operand_row,operand_k[5:0]};
    // Eight column lanes, each split into even/odd k banks of 16x1024.
    // A packed DMA word writes both parity banks on the same edge.
    wire [9:0] wa = wwrite ? {load_addr[15:11],load_addr[7:3]} : {operand_group,operand_k[5:1]};
    wire prefetch_req = state==MAC && (k<=30 && k[1]);
    wire prefetch_capture = state==MAC && (k>=4 && k<=32 && !k[1]);
    wire [2:0] prefetch_lane=k[4:2];
    wire [4:0] next_group = col[7:3]+5'd1;
    wire [9:0] ba = bwrite ? {2'b0,load_addr[9:2]} :
        (prefetch_req ? {2'b0,next_group,prefetch_lane} : {2'b0,col[7:3],bias_lane});
    wire [15:0] xd [0:1];
    wire [15:0] wd [0:7][0:1];
    wire [15:0] bl, bh, b2l,b2h;
    wire [15:0] wd2 [0:7][0:1];
    wire [15:0] gd [0:1];
    wire [9:0] wa2=w2write ? {load_addr[15:13],load_addr[9:3]} : {operand_group[2:0],operand_k[7:1]};
    wire [2:0] next_group2=col[5:3]+3'd1;
    wire [6:0] ba2=b2write ? {1'b0,load_addr[7:2]} :
        (prefetch_req ? {1'b0,next_group2,prefetch_lane} : {1'b0,col[5:3],bias_lane});
    wire signed [15:0] gelu_result;
    wire gelu_saturated;
    // Eight rows per tile reuse the same two parity banks. The scalar GELU
    // worker owns the write address while first-layer MACs run independently.
    wire [9:0] ga=gelu_busy ? {gelu_row,gelu_group,gelu_lane[2:1]} : {operand_row[2:0],operand_k[7:1]};
    kwt_gelu activation(.value(merged[gelu_lane]),.input_shift(gelu_input_shift),
        .output_shift(gelu_output_shift),.result(gelu_result),.saturated(gelu_saturated));
    reg xb;
    wire signed [39:0] acc [0:7];
    genvar i,p;
    generate for (i=0;i<2;i=i+1) begin: xbanks
        kwt_sram16 xm(.clk(clk),
            .cs((xwrite && (dma_mode || xa[0]==(i==1))) || (read_operands && !second_stage)),
            .we(xwrite),.addr(xa[12:1]),.din(dma_mode && i==1 ? load_data[31:16] : load_data[15:0]),.dout(xd[i]));
    end
    for (i=0;i<8;i=i+1) begin: wbanks
        for(p=0;p<2;p=p+1) begin: parity
            kwt_sram16 #(.AW(10)) wm(.clk(clk),
                .cs((read_operands && !second_stage) ||
                    (wwrite && load_addr[10:8]==i && (dma_mode || load_addr[2]==(p==1)))),
                .we(wwrite),.addr(wa),.din(dma_mode && p==1 ? load_data[31:16] : load_data[15:0]),.dout(wd[i][p]));
        end
        for(p=0;p<2;p=p+1) begin: second_weights
            kwt_sram16 #(.AW(10)) wm2(.clk(clk),
                .cs((read_operands && second_stage) || (w2write && load_addr[12:10]==i)),
                .we(w2write),.addr(wa2),.din(p==1 ? load_data[31:16] : load_data[15:0]),.dout(wd2[i][p]));
        end
        kwt_mac40 mac(.clk(clk),.rst_n(rst_n),.init(mac_init),
            .enable(mac_enable),.x(second_stage ? gd[xb] : xd[xb]),.w(second_stage ? wd2[i][xb] : wd[i][xb]),.bias(next_bias[i]),.acc(acc[i]));
        kwt_mac40 odd_mac(.clk(clk),.rst_n(rst_n),.init(mac_init),
            .enable(mac_enable),.x(second_stage ? gd[1] : xd[1]),
            .w(second_stage ? wd2[i][1] : wd[i][1]),.bias(32'sd0),.acc(odd_acc[i]));
        // Register the exact partial-sum merge before GELU to avoid adding a
        // 40-bit adder to its combinational path. Payload validity is the FSM.
        always @(posedge clk) if(merge_fire) merged[i]<=acc[i]+odd_acc[i];
    end
    for(i=0;i<2;i=i+1) begin: intermediate
        kwt_sram16 #(.AW(10)) gm(.clk(clk),
            .cs((gelu_busy && gelu_lane[0]==(i==1)) || (read_operands && second_stage)),
            .we(gelu_busy),.addr(ga),.din(gelu_result),.dout(gd[i]));
    end
    endgenerate
    kwt_sram16 #(.AW(10)) bmlo(.clk(clk),.cs(bwrite || (!second_stage && (state==BREQ || prefetch_req))),.we(bwrite),.addr(ba),.din(load_data[15:0]),.dout(bl));
    kwt_sram16 #(.AW(10)) bmhi(.clk(clk),.cs(bwrite || (!second_stage && (state==BREQ || prefetch_req))),.we(bwrite),.addr(ba),.din(load_data[31:16]),.dout(bh));
    kwt_sram16 #(.AW(7)) bm2lo(.clk(clk),.cs(b2write || (second_stage && (state==BREQ || prefetch_req))),
        .we(b2write),.addr(ba2),.din(load_data[15:0]),.dout(b2l));
    kwt_sram16 #(.AW(7)) bm2hi(.clk(clk),.cs(b2write || (second_stage && (state==BREQ || prefetch_req))),
        .we(b2write),.addr(ba2),.din(load_data[31:16]),.dout(b2h));
    wire [39:0] result = fifo[head];
    assign cmd_ready = !dma_mode && (!rsp_valid || rsp_ready);
    // X writes use idle input-bank slots, including a stalled L2 output.
    // This lets LN1 finish even while the tail consumer has not started.
    assign dma_load_ready = !busy || (full_ffn && !second_stage && (w2sel || b2sel)) ||
        (dma_input_stream && xsel && !(read_operands && !second_stage));
    assign dma_out_valid = count != 0;
    assign dma_out_data = {{24{result[39]}},result};
    assign dma_done=done;
    assign dma_fault=fault;
    assign perf_cycles=cycles;
    assign perf_mac_cycles=mac_cycles;
    assign perf_fifo_wait=fifo_wait;
    // Bias payload is intentionally unreset; BREQ/BLOAD fill all lanes before
    // first use. Later groups prefetch into it while the current MACs run.
    always @(posedge clk) begin
        if(state==BLOAD) next_bias[bias_lane]<=second_stage ? {b2h,b2l} : {bh,bl};
        if(prefetch_capture) next_bias[bias_return_lane]<=second_stage ? {b2h,b2l} : {bh,bl};
    end
    integer lane;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; second_stage<=0;gelu_lane<=0;nw2<=0;nb2<=0; row<=0; col<=0; k<=0; nx<=0; nw<=0; nb<=0;
            done<=0; fault<=0; cycles<=0; xb<=0; bias_lane<=0; bias_return_lane<=0;
            mac_cycles<=0; fifo_wait<=0;
            perf_second_mac<=0;perf_gelu<=0;perf_saturation<=0;perf_gelu_overlap<=0;perf_parameter_wait<=0;
            gelu_busy<=0;gelu_group<=0;gelu_row<=0;
            head<=0; tail<=0; count<=0; outputs_read<=0;
            rsp_valid<=0; rsp_rdata<=0; rsp_err<=0;
        end else begin
            if (rsp_valid && rsp_ready) rsp_valid<=0;
            if (busy) cycles<=cycles+1;
            if (state==MAC || state==LAST) mac_cycles<=mac_cycles+1;
            if(second_stage && (state==MAC || state==LAST)) perf_second_mac<=perf_second_mac+1;
            if(gelu_busy) begin
                perf_gelu<=perf_gelu+1;
                if(mac_enable) perf_gelu_overlap<=perf_gelu_overlap+1;
                if(gelu_saturated) perf_saturation<=perf_saturation+1;
                gelu_lane<=gelu_lane+1'b1;
                if(gelu_lane==7) gelu_busy<=0;
            end
            // GELU denotes the tile barrier, not the worker's activity state.
            if(state==GELU) begin
                if(!gelu_busy && !second_ready) perf_parameter_wait<=perf_parameter_wait+1;
                if(!gelu_busy && second_ready) begin
                    second_stage<=1;row<={row[6:3],3'b000};col<=0;
                    bias_lane<=0;k<=0;state<=BREQ;
                end
            end
            if (state==EMIT && !push) fifo_wait<=fifo_wait+1;
            if (dma_mode && ((load && !(xwrite || wwrite || bwrite || w2write || b2write)) ||
                (dma_start && (busy || !complete_load)))) fault<=1;
            if(state==WAIT_X && nx >= (row>=96 ? 13'd6336 : ({6'd0,row[6:3],3'd0}+13'd8)<<6)) state<=BREQ;
            if (state==BREQ) state<=BLOAD;
            if (state==BLOAD) begin
                bias_lane<=bias_lane+1'b1;
                if (bias_lane==7) begin k<=0; state<=PRIME; end
                else state<=BREQ;
            end
            // Registered SRAM operands from the preceding edge are consumed
            // while the next operands are read. LAST drains the final scalar or pair.
            if (prefetch_req) bias_return_lane<=prefetch_lane;
            if (read_operands) xb<=xa[0];
            if (state==PRIME) begin k<=k_step; state<=MAC; end
            if (state==MAC) begin
                if (k==(second_stage ? 8'd255 : 8'd63)-8'd1) state<=LAST;
                else k<=k+k_step;
            end
            if (state==LAST) state<=(OUTPUT_MERGE_FUSED!=0 && !(full_ffn && !second_stage)) ? EMIT : MERGE;
            if (merge_fire) begin
                if(full_ffn && !second_stage) begin
                    gelu_busy<=1;gelu_lane<=0;gelu_group<=col[7:3];gelu_row<=row[2:0];
                    k<=prime_next ? 8'd2 : 8'd0;col<=col+8'd8;state<=prime_next ? MAC : PRIME;
                    if(col==248) begin
                        if(row[2:0]==7 || row==98) state<=GELU;
                        else begin row<=row+1'b1;col<=0;end
                    end
                end else state<=EMIT;
            end
            case ({push,pop})
                2'b10: count<=count+5'd8;
                2'b01: count<=count-1'b1;
                2'b11: count<=count+5'd7;
                default: begin end
            endcase
            if (push) begin
                // Nonblocking writes capture the old sums before prime_next
                // initializes the MACs. Under backpressure the sums stay held.
                for(lane=0;lane<8;lane=lane+1) fifo[tail+4'(lane)]<=OUTPUT_MERGE_FUSED!=0 ? acc[lane]+odd_acc[lane] : merged[lane];
                tail<=tail+4'd8;
                if (col==(second_stage ? 8'd56 : 8'd248) && row==98) state<=DRAIN;
                else begin
                    col<=col+8'd8;
                    k<=prime_next ? 8'd2 : 8'd0; state<=prime_next ? MAC : PRIME;
                    if(second_stage && col==56) begin
                        row<=row+1'b1;col<=0;
                        if(row[2:0]==7) begin second_stage<=0;bias_lane<=0;state<=dma_input_stream ? WAIT_X : BREQ;end
                    end else if(!second_stage && col==248) row<=row+1'b1;
                end
            end
            if (pop) begin
                head<=head+1'b1; outputs_read<=outputs_read+1'b1;
                if (outputs_read==(full_ffn ? 15'd6335 : 15'd25343)) begin state<=IDLE; done<=1; end
            end
            if (xwrite) nx<=nx+(dma_mode ? 13'd2 : 13'd1);
            if (wwrite) nw<=nw+(dma_mode ? 15'd2 : 15'd1);
            if (bwrite) nb<=nb+1'b1;
            if (w2write) nw2<=nw2+15'd2;
            if (b2write) nb2<=nb2+1'b1;
            if (start) begin
                state<=BREQ; second_stage<=0;gelu_lane<=0; row<=0; col<=0; bias_lane<=0; done<=0; cycles<=0;
                mac_cycles<=0; fifo_wait<=0;
                perf_second_mac<=0;perf_gelu<=0;perf_saturation<=0;perf_gelu_overlap<=0;perf_parameter_wait<=0;
            gelu_busy<=0;gelu_group<=0;gelu_row<=0;
                head<=0; tail<=0; count<=0; outputs_read<=0;
            end
            if (clear) begin
                state<=IDLE; second_stage<=0;gelu_lane<=0;nw2<=0;nb2<=0; nx<=0; nw<=0; nb<=0; done<=0; fault<=0; cycles<=0;
                mac_cycles<=0; fifo_wait<=0;
                perf_second_mac<=0;perf_gelu<=0;perf_saturation<=0;perf_gelu_overlap<=0;perf_parameter_wait<=0;
            gelu_busy<=0;gelu_group<=0;gelu_row<=0;
                head<=0; tail<=0; count<=0; outputs_read<=0; bias_lane<=0;
            end
            if (take) begin
                rsp_valid<=1; rsp_rdata<=0; rsp_err<=0;
                if (cmd_read && aligned) begin
                    case (cmd_addr)
                        20'h04: rsp_rdata<={27'b0,(count>=4),fault,(count!=0),done,busy};
                        20'h08: rsp_rdata<=cycles;
                        20'h0c: rsp_rdata<=32'h4b575431;
                        20'h10: if (count!=0) rsp_rdata<=result[31:0]; else begin rsp_err<=1; fault<=1; end
                        20'h14: if (count!=0) rsp_rdata<={{24{result[39]}},result[39:32]}; else begin rsp_err<=1; fault<=1; end
                        default: begin rsp_err<=1; fault<=1; end
                    endcase
                end else if (!(xwrite || wwrite || bwrite || start || clear)) begin
                    rsp_err<=1; fault<=1;
                end
            end
        end
    end
endmodule
