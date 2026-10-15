// One outstanding 32-bit ICB transaction. Offsets are relative to 0x40000000.
// X/W use one sign-extended 16-bit element per 32-bit bus word, W column-major.
module kwt_accel(
    input wire clk, rst_n,
    input wire cmd_valid, output wire cmd_ready,
    input wire [19:0] cmd_addr, input wire cmd_read,
    input wire [31:0] cmd_wdata, input wire [3:0] cmd_wmask,
    output reg rsp_valid, input wire rsp_ready,
    output reg [31:0] rsp_rdata, output reg rsp_err
);
    localparam IDLE=3'd0, BREQ=3'd1, BLOAD=3'd2, READ=3'd3, MAC=3'd4, EMIT=3'd5;
    reg [2:0] state;
    reg [6:0] row;
    reg [7:0] col;
    reg [5:0] k;
    reg [12:0] nx;
    reg [14:0] nw;
    reg [8:0] nb;
    reg done, fault;
    reg [31:0] cycles;
    wire busy = state != IDLE;
    wire take = cmd_valid && cmd_ready;
    wire aligned = cmd_addr[1:0] == 0;
    wire xsel = cmd_addr >= 20'h10000 && cmd_addr < 20'h16300;
    wire wsel = cmd_addr >= 20'h20000 && cmd_addr < 20'h30000;
    wire bsel = cmd_addr >= 20'h30000 && cmd_addr < 20'h30400;
    wire load = take && !cmd_read && aligned && cmd_wmask == 4'hf && !busy;
    wire xwrite = load && xsel && cmd_addr[14:2] == nx && nx < 6336;
    wire wwrite = load && wsel && cmd_addr[15:2] == nw[13:0] && nw < 16384;
    wire bwrite = load && bsel && cmd_addr[9:2] == nb[7:0] && nb < 256;
    wire start = load && cmd_addr == 0 && cmd_wdata == 1 && nx == 6336 && nw == 16384 && nb == 256;
    wire clear = take && !cmd_read && cmd_addr == 0 && cmd_wmask == 4'hf && cmd_wdata == 2;
    wire pop = take && cmd_read && cmd_addr == 20'h14 && state == EMIT;
    wire [12:0] xa = xwrite ? cmd_addr[14:2] : {row,k};
    wire [13:0] wa = wwrite ? cmd_addr[15:2] : {col,k};
    wire [9:0] ba = bwrite ? {2'b0,cmd_addr[9:2]} : {2'b0,col};
    wire [15:0] xd [0:1];
    wire [15:0] wd [0:3];
    wire [15:0] bl, bh;
    reg xb;
    reg [1:0] wb;
    genvar i;
    generate for (i=0;i<2;i=i+1) begin: xbanks
        kwt_sram16 xm(.clk(clk),.cs((xwrite || state==READ) && xa[12]==(i==1)),
            .we(xwrite),.addr(xa[11:0]),.din(cmd_wdata[15:0]),.dout(xd[i]));
    end
    for (i=0;i<4;i=i+1) begin: wbanks
        kwt_sram16 wm(.clk(clk),.cs((wwrite || state==READ) && wa[13:12]==i),
            .we(wwrite),.addr(wa[11:0]),.din(cmd_wdata[15:0]),.dout(wd[i]));
    end endgenerate
    kwt_sram16 #(.AW(10)) bmlo(.clk(clk),.cs(bwrite || state==BREQ),.we(bwrite),.addr(ba),.din(cmd_wdata[15:0]),.dout(bl));
    kwt_sram16 #(.AW(10)) bmhi(.clk(clk),.cs(bwrite || state==BREQ),.we(bwrite),.addr(ba),.din(cmd_wdata[31:16]),.dout(bh));
    wire signed [39:0] acc;
    kwt_mac40 mac(.clk(clk),.rst_n(rst_n),.init(state==BLOAD),.enable(state==MAC),
        .x(xd[xb]),.w(wd[wb]),.bias({bh,bl}),.acc(acc));
    assign cmd_ready = !rsp_valid;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; row<=0; col<=0; k<=0; nx<=0; nw<=0; nb<=0;
            done<=0; fault<=0; cycles<=0; xb<=0; wb<=0;
            rsp_valid<=0; rsp_rdata<=0; rsp_err<=0;
        end else begin
            if (rsp_valid && rsp_ready) rsp_valid<=0;
            if (busy) cycles<=cycles+1;
            if (state==BREQ) state<=BLOAD;
            if (state==BLOAD) begin k<=0; state<=READ; end
            if (state==READ) begin xb<=xa[12]; wb<=wa[13:12]; state<=MAC; end
            if (state==MAC) begin
                if (k==63) state<=EMIT;
                else begin k<=k+1'b1; state<=READ; end
            end
            if (pop) begin
                if (col==255 && row==98) begin state<=IDLE; done<=1; end
                else begin
                    col<=col+1'b1;
                    if (col==255) row<=row+1'b1;
                    state<=BREQ;
                end
            end
            if (xwrite) nx<=nx+1'b1;
            if (wwrite) nw<=nw+1'b1;
            if (bwrite) nb<=nb+1'b1;
            if (start) begin state<=BREQ; row<=0; col<=0; done<=0; cycles<=0; end
            if (clear) begin
                state<=IDLE; nx<=0; nw<=0; nb<=0; done<=0; fault<=0; cycles<=0;
            end
            if (take) begin
                rsp_valid<=1; rsp_rdata<=0; rsp_err<=0;
                if (cmd_read && aligned) begin
                    case (cmd_addr)
                        20'h04: rsp_rdata<={28'b0,fault,(state==EMIT),done,busy};
                        20'h08: rsp_rdata<=cycles;
                        20'h0c: rsp_rdata<=32'h4b575431;
                        20'h10: if (state==EMIT) rsp_rdata<=acc[31:0]; else begin rsp_err<=1; fault<=1; end
                        20'h14: if (state==EMIT) rsp_rdata<={{24{acc[39]}},acc[39:32]}; else begin rsp_err<=1; fault<=1; end
                        default: begin rsp_err<=1; fault<=1; end
                    endcase
                end else if (!(xwrite || wwrite || bwrite || start || clear)) begin
                    rsp_err<=1; fault<=1;
                end
            end
        end
    end
endmodule
