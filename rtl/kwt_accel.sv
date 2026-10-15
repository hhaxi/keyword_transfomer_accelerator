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
    input wire dma_start, dma_clear, output wire dma_out_valid,
    output wire [63:0] dma_out_data, input wire dma_out_ready,
    output wire dma_done, dma_fault,
    output wire [31:0] perf_cycles, perf_mac_cycles, perf_fifo_wait
);
    localparam IDLE=3'd0, BREQ=3'd1, BLOAD=3'd2, PRIME=3'd3,
               MAC=3'd4, LAST=3'd5, EMIT=3'd6, DRAIN=3'd7;
    reg [2:0] state;
    reg [6:0] row;
    reg [7:0] col;
    reg [5:0] k;
    reg [2:0] bias_lane, bias_return_lane;
    reg [31:0] next_bias [0:7];
    // Two groups decouple eight parallel MACs from scalar output transfers.
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
    wire complete_load = nx == 6336 && nw == 16384 && nb == 256;
    wire start = !busy && complete_load && (dma_mode ? dma_start :
                 (load && cmd_addr == 0 && cmd_wdata == 1));
    wire clear = dma_mode ? dma_clear :
                 (take && !cmd_read && cmd_addr == 0 && cmd_wmask == 4'hf && cmd_wdata == 2);
    wire pop = count != 0 && (dma_mode ? dma_out_ready :
               (take && cmd_read && cmd_addr == 20'h14));
    wire push = state == EMIT && count <= 8;
    wire read_operands = state == PRIME || state == MAC;
    wire [12:0] xa = xwrite ? load_addr[14:2] : {row,k};
    // Eight column lanes, each split into even/odd k banks of 16x1024.
    // A packed DMA word writes both parity banks on the same edge.
    wire [9:0] wa = wwrite ? {load_addr[15:11],load_addr[7:3]} : {col[7:3],k[5:1]};
    wire prefetch_req = state==MAC && k<=15 && k[0];
    wire prefetch_capture = state==MAC && k>=2 && k<=16 && !k[0];
    wire [4:0] next_group = col[7:3]+5'd1;
    wire [9:0] ba = bwrite ? {2'b0,load_addr[9:2]} :
        (prefetch_req ? {2'b0,next_group,k[3:1]} : {2'b0,col[7:3],bias_lane});
    wire [15:0] xd [0:1];
    wire [15:0] wd [0:7][0:1];
    wire [15:0] bl, bh;
    reg xb;
    wire signed [39:0] acc [0:7];
    genvar i,p;
    generate for (i=0;i<2;i=i+1) begin: xbanks
        kwt_sram16 xm(.clk(clk),
            .cs((xwrite && (dma_mode || xa[0]==(i==1))) || (read_operands && xa[0]==(i==1))),
            .we(xwrite),.addr(xa[12:1]),.din(dma_mode && i==1 ? load_data[31:16] : load_data[15:0]),.dout(xd[i]));
    end
    for (i=0;i<8;i=i+1) begin: wbanks
        for(p=0;p<2;p=p+1) begin: parity
            kwt_sram16 #(.AW(10)) wm(.clk(clk),
                .cs((read_operands && k[0]==(p==1)) ||
                    (wwrite && load_addr[10:8]==i && (dma_mode || load_addr[2]==(p==1)))),
                .we(wwrite),.addr(wa),.din(dma_mode && p==1 ? load_data[31:16] : load_data[15:0]),.dout(wd[i][p]));
        end
        kwt_mac40 mac(.clk(clk),.rst_n(rst_n),.init(state==PRIME),
            .enable(state==MAC || state==LAST),.x(xd[xb]),.w(wd[i][xb]),.bias(next_bias[i]),.acc(acc[i]));
    end endgenerate
    kwt_sram16 #(.AW(10)) bmlo(.clk(clk),.cs(bwrite || state==BREQ || prefetch_req),.we(bwrite),.addr(ba),.din(load_data[15:0]),.dout(bl));
    kwt_sram16 #(.AW(10)) bmhi(.clk(clk),.cs(bwrite || state==BREQ || prefetch_req),.we(bwrite),.addr(ba),.din(load_data[31:16]),.dout(bh));
    wire [39:0] result = fifo[head];
    assign cmd_ready = !dma_mode && (!rsp_valid || rsp_ready);
    assign dma_load_ready = !busy;
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
        if(state==BLOAD) next_bias[bias_lane]<={bh,bl};
        if(prefetch_capture) next_bias[bias_return_lane]<={bh,bl};
    end
    integer lane;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; row<=0; col<=0; k<=0; nx<=0; nw<=0; nb<=0;
            done<=0; fault<=0; cycles<=0; xb<=0; bias_lane<=0; bias_return_lane<=0;
            mac_cycles<=0; fifo_wait<=0;
            head<=0; tail<=0; count<=0; outputs_read<=0;
            rsp_valid<=0; rsp_rdata<=0; rsp_err<=0;
        end else begin
            if (rsp_valid && rsp_ready) rsp_valid<=0;
            if (busy) cycles<=cycles+1;
            if (state==MAC || state==LAST) mac_cycles<=mac_cycles+1;
            if (state==EMIT && !push) fifo_wait<=fifo_wait+1;
            if (dma_mode && ((load && !(xwrite || wwrite || bwrite)) ||
                (dma_start && (busy || !complete_load)))) fault<=1;
            if (state==BREQ) state<=BLOAD;
            if (state==BLOAD) begin
                bias_lane<=bias_lane+1'b1;
                if (bias_lane==7) begin k<=0; state<=PRIME; end
                else state<=BREQ;
            end
            // Registered SRAM operands from the preceding edge are consumed
            // while the next pair is read. LAST drains operand 63 exactly once.
            if (prefetch_req) bias_return_lane<=k[3:1];
            if (read_operands) xb<=xa[0];
            if (state==PRIME) begin k<=1; state<=MAC; end
            if (state==MAC) begin
                if (k==63) state<=LAST;
                else k<=k+1'b1;
            end
            if (state==LAST) state<=EMIT;
            case ({push,pop})
                2'b10: count<=count+5'd8;
                2'b01: count<=count-1'b1;
                2'b11: count<=count+5'd7;
                default: begin end
            endcase
            if (push) begin
                for(lane=0;lane<8;lane=lane+1) fifo[tail+4'(lane)]<=acc[lane];
                tail<=tail+4'd8;
                if (col==248 && row==98) state<=DRAIN;
                else begin
                    col<=col+8'd8;
                    if (col==248) row<=row+1'b1;
                    k<=0; state<=PRIME;
                end
            end
            if (pop) begin
                head<=head+1'b1; outputs_read<=outputs_read+1'b1;
                if (outputs_read==25343) begin state<=IDLE; done<=1; end
            end
            if (xwrite) nx<=nx+(dma_mode ? 13'd2 : 13'd1);
            if (wwrite) nw<=nw+(dma_mode ? 15'd2 : 15'd1);
            if (bwrite) nb<=nb+1'b1;
            if (start) begin
                state<=BREQ; row<=0; col<=0; bias_lane<=0; done<=0; cycles<=0;
                mac_cycles<=0; fifo_wait<=0;
                head<=0; tail<=0; count<=0; outputs_read<=0;
            end
            if (clear) begin
                state<=IDLE; nx<=0; nw<=0; nb<=0; done<=0; fault<=0; cycles<=0;
                mac_cycles<=0; fifo_wait<=0;
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
