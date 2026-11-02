// Fixed 99x64 * 64x256 + bias. Eight columns, two k values per cycle.
// Synchronous single-port banks; unchanged INT16/INT32/INT40 arithmetic.
module kwt_ffn1_core(
    input wire clk,rst_n,
    input wire dma_load_valid,input wire [19:0] dma_load_addr,
    input wire [31:0] dma_load_data,output wire dma_load_ready,
    input wire dma_start,dma_clear,
    output wire dma_out_valid,output wire [63:0] dma_out_data,input wire dma_out_ready,
    output wire dma_done,dma_fault,
    output wire [31:0] perf_cycles,perf_mac_cycles,perf_fifo_wait
);
    localparam IDLE=0,BREQ=1,BLOAD=2,PRIME=3,MAC=4,LAST=5,EMIT=6,DRAIN=7;
    reg [2:0] state;
    reg [6:0] row;reg [7:0] col,k;
    reg [2:0] bias_lane,bias_return_lane;
    reg [31:0] next_bias[0:7];
    reg [12:0] nx;reg [14:0] nw;reg [8:0] nb;
    reg [39:0] fifo[0:15];reg [3:0] head,tail;reg [4:0] count;
    reg [14:0] outputs_read;
    reg done,fault,xb;
    reg [31:0] cycles,mac_cycles,fifo_wait;
    wire busy=state!=IDLE;
    wire [19:0] load_addr=dma_load_addr;
    wire [31:0] load_data=dma_load_data;
    wire load=dma_load_valid && dma_load_ready;
    wire xwrite=load && load_addr>=20'h10000 && load_addr<20'h16300 && load_addr[2:0]==0 && load_addr[14:2]==nx && nx<6336;
    wire wwrite=load && load_addr>=20'h20000 && load_addr<20'h30000 && load_addr[2:0]==0 && load_addr[15:2]==nw[13:0] && nw<16384;
    wire bwrite=load && load_addr>=20'h30000 && load_addr<20'h30400 && load_addr[1:0]==0 && load_addr[9:2]==nb[7:0] && nb<256;
    wire complete_load=nx==6336 && nw==16384 && nb==256;
    wire start=!busy && complete_load && dma_start;
    wire pop=count!=0 && dma_out_ready;
    wire push=state==EMIT && count<=8;
    wire group_last=col==248;
    wire prime_next=!(group_last && row==98) && push;
    wire [6:0] operand_row=prime_next && group_last ? row+7'd1 : row;
    wire [4:0] operand_group=prime_next ? (group_last ? 5'd0 : col[7:3]+5'd1) : col[7:3];
    wire [7:0] operand_k=prime_next ? 8'd0 : k;
    wire read_operands=state==PRIME || state==MAC || prime_next;
    wire mac_init=state==PRIME || prime_next;
    wire mac_enable=state==MAC || state==LAST;
    wire [12:0] xa=xwrite ? load_addr[14:2] : {operand_row,operand_k[5:0]};
    wire [9:0] wa=wwrite ? {load_addr[15:11],load_addr[7:3]} : {operand_group,operand_k[5:1]};
    wire prefetch_req=state==MAC && k<=30 && k[1];
    wire prefetch_capture=state==MAC && k>=4 && k<=32 && !k[1];
    wire [2:0] prefetch_lane=k[4:2];
    wire [4:0] next_group=col[7:3]+5'd1;
    wire [9:0] ba=bwrite ? {2'b0,load_addr[9:2]} :
        (prefetch_req ? {2'b0,next_group,prefetch_lane} : {2'b0,col[7:3],bias_lane});
    wire [15:0] xd[0:1],wd[0:7][0:1];
    wire [15:0] bl,bh;
    wire signed [39:0] acc[0:7],odd_acc[0:7];
    genvar i,p;
    generate
        for(i=0;i<2;i=i+1) begin: xbanks
            kwt_sram16 xm(.clk(clk),.cs(xwrite || read_operands),.we(xwrite),
                .addr(xa[12:1]),.din(i==1 ? load_data[31:16] : load_data[15:0]),.dout(xd[i]));
        end
        for(i=0;i<8;i=i+1) begin: wbanks
            for(p=0;p<2;p=p+1) begin: parity
                kwt_sram16 #(.AW(10)) wm(.clk(clk),
                    .cs(read_operands || (wwrite && load_addr[10:8]==i)),.we(wwrite),
                    .addr(wa),.din(p==1 ? load_data[31:16] : load_data[15:0]),.dout(wd[i][p]));
            end
            kwt_mac40 mac(.clk(clk),.rst_n(rst_n),.init(mac_init),.enable(mac_enable),
                .x(xd[xb]),.w(wd[i][xb]),.bias(next_bias[i]),.acc(acc[i]));
            kwt_mac40 odd_mac(.clk(clk),.rst_n(rst_n),.init(mac_init),.enable(mac_enable),
                .x(xd[1]),.w(wd[i][1]),.bias(32'sd0),.acc(odd_acc[i]));
        end
    endgenerate
    kwt_sram16 #(.AW(10)) bmlo(.clk(clk),.cs(bwrite || state==BREQ || prefetch_req),
        .we(bwrite),.addr(ba),.din(load_data[15:0]),.dout(bl));
    kwt_sram16 #(.AW(10)) bmhi(.clk(clk),.cs(bwrite || state==BREQ || prefetch_req),
        .we(bwrite),.addr(ba),.din(load_data[31:16]),.dout(bh));
    wire [39:0] result=fifo[head];
    assign dma_load_ready=!busy;
    assign dma_out_valid=count!=0;
    assign dma_out_data={{24{result[39]}},result};
    assign dma_done=done;assign dma_fault=fault;
    assign perf_cycles=cycles;assign perf_mac_cycles=mac_cycles;assign perf_fifo_wait=fifo_wait;
    always @(posedge clk) begin
        if(state==BLOAD) next_bias[bias_lane]<={bh,bl};
        if(prefetch_capture) next_bias[bias_return_lane]<={bh,bl};
    end
    integer lane;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;row<=0;col<=0;k<=0;nx<=0;nw<=0;nb<=0;
            bias_lane<=0;bias_return_lane<=0;done<=0;fault<=0;xb<=0;
            head<=0;tail<=0;count<=0;outputs_read<=0;
            cycles<=0;mac_cycles<=0;fifo_wait<=0;
        end else begin
            if(busy) cycles<=cycles+1;
            if(mac_enable) mac_cycles<=mac_cycles+1;
            if(state==EMIT && !push) fifo_wait<=fifo_wait+1;
            if((load && !(xwrite || wwrite || bwrite)) || (dma_start && (busy || !complete_load))) fault<=1;
            if(state==BREQ) state<=BLOAD;
            if(state==BLOAD) begin
                bias_lane<=bias_lane+1'b1;
                if(bias_lane==7) begin k<=0;state<=PRIME;end else state<=BREQ;
            end
            if(prefetch_req) bias_return_lane<=prefetch_lane;
            if(read_operands) xb<=xa[0];
            if(state==PRIME) begin k<=2;state<=MAC;end
            if(state==MAC) begin if(k==62) state<=LAST;else k<=k+2;end
            if(state==LAST) state<=EMIT;
            case({push,pop})
                2'b10:count<=count+8;
                2'b01:count<=count-1'b1;
                2'b11:count<=count+7;
                default:begin end
            endcase
            if(push) begin
                for(lane=0;lane<8;lane=lane+1) fifo[tail+4'(lane)]<=acc[lane]+odd_acc[lane];
                tail<=tail+8;
                if(group_last && row==98) state<=DRAIN;
                else begin
                    col<=col+8;k<=prime_next ? 8'd2 : 8'd0;state<=prime_next ? MAC : PRIME;
                    if(group_last) row<=row+1'b1;
                end
            end
            if(pop) begin
                head<=head+1'b1;outputs_read<=outputs_read+1'b1;
                if(outputs_read==25343) begin state<=IDLE;done<=1;end
            end
            if(xwrite) nx<=nx+2;
            if(wwrite) nw<=nw+2;
            if(bwrite) nb<=nb+1'b1;
            if(start) begin
                state<=BREQ;row<=0;col<=0;k<=0;bias_lane<=0;done<=0;
                head<=0;tail<=0;count<=0;outputs_read<=0;cycles<=0;mac_cycles<=0;fifo_wait<=0;
            end
            if(dma_clear) begin
                state<=IDLE;row<=0;col<=0;k<=0;nx<=0;nw<=0;nb<=0;
                done<=0;fault<=0;head<=0;tail<=0;count<=0;outputs_read<=0;
                bias_lane<=0;bias_return_lane<=0;cycles<=0;mac_cycles<=0;fifo_wait<=0;
            end
        end
    end
endmodule
