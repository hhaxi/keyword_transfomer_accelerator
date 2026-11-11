// R4C4K1 uses output-stationary broadcast, not neighbor-forwarding systolic links.
module kwt_tile_core #(parameter ROWS=1,COLS=8,KPAR=2,FUSE=0,PRODUCT_PIPE=0,SMALL_BIAS=0)(
 input wire clk,rst_n,input wire dma_load_valid,input wire [19:0] dma_load_addr,
 input wire [31:0] dma_load_data,output wire dma_load_ready,
 input wire dma_start,dma_clear,output wire [1:0] dma_x_free,
 output wire dma_out_valid,output wire [63:0] dma_out_data,
 output wire [14:0] dma_out_index,input wire dma_out_ready,
 output wire dma_done,dma_fault,output wire [31:0] perf_cycles,perf_mac_cycles,perf_fifo_wait);
 // Supported schedules preserve fixed, static physical PE counts.
 generate if(!((ROWS==1 && COLS==8 && KPAR==2) ||
               (ROWS==2 && COLS==8 && KPAR==2) ||
               (ROWS==4 && COLS==4 && KPAR==1)))begin:unsupported
  KWT_UNSUPPORTED_TILE_GEOMETRY invalid_configuration();
 end endgenerate
 localparam RL=$clog2(ROWS),CL=$clog2(COLS);
 localparam IDLE=0,BREQ=1,BLOAD=2,PRIME=3,MAC=4,LAST=5,PIPE=6,EMIT=7,WAIT_TILE=8,DRAIN=9;
 reg [3:0] state;reg [6:0] row;reg [7:0] col;reg [6:0] k;
 reg [1:0] x_valid;reg [11:0] nx;reg [13:0] nw;reg [8:0] nb;
 reg [2:0] bias_lane,return_lane;reg [31:0] bias[0:COLS-1];reg first,operand_parity,read_tile,prefetched;
 reg [39:0] fifo[0:63];reg [14:0] indices[0:63];reg [5:0] head,tail;
 reg [6:0] count;reg [14:0] popped;reg done,fault;reg [31:0] cycles,mac_cycles,fifo_wait;
 wire busy=state!=IDLE;wire [6:0] load_row=dma_load_addr[14:8];wire load_tile=(load_row>>RL)&1;
 wire xspace=dma_load_addr>=20'h10000 && dma_load_addr<20'h16300;
 assign dma_load_ready=xspace ? !x_valid[load_tile] : !busy;
 wire load=dma_load_valid && dma_load_ready;
 wire xwrite=load && xspace && dma_load_addr[2:0]==0 && dma_load_addr[14:3]==nx && nx<3168;
 wire wwrite=load && dma_load_addr>=20'h20000 && dma_load_addr<20'h30000 && dma_load_addr[2:0]==0 && dma_load_addr[15:3]==nw[12:0] && nw<8192;
 wire bwrite=load && dma_load_addr>=20'h30000 && dma_load_addr<20'h30400 && dma_load_addr[1:0]==0 && dma_load_addr[9:2]==nb[7:0] && nb<256;
 wire complete_load=x_valid[0] && nw==8192 && nb==256;
 wire start=dma_start && !busy && complete_load;
 wire pop=count!=0 && dma_out_ready;
 wire [6:0] valid_rows=(row+ROWS>99) ? 99-row : ROWS;
 wire [6:0] batch=valid_rows<<CL;
 wire push=state==EMIT && count<=64-batch;
 wire group_last=col==256-COLS;
 wire final_group=group_last && row+ROWS>=99;
 wire tile_bank=(row>>RL)&1;wire next_tile_valid=x_valid[!tile_bank];
 wire next_available=!final_group && (!group_last || next_tile_valid);
 // SRAM request at LAST/PIPE returns before EMIT. Fused EMIT commits old acc
 // and seeds the next group on the same edge, including registered products.
 wire early_read=FUSE && (state==LAST || state==PIPE) && next_available;
 wire fused_seed=FUSE && push && prefetched && next_available;
 wire prime_next=push && next_available;
 wire next_address=early_read || prime_next;
 wire [6:0] operand_row=(next_address && group_last) ? row+ROWS : row;
 wire [7:0] operand_col=next_address ? (group_last ? 0 : col+COLS) : col;
 wire [6:0] operand_k=next_address ? (fused_seed ? KPAR : 0) : k;
 wire read_operands=state==PRIME || state==MAC || next_address;
 wire product_valid=state==MAC || state==LAST || fused_seed;
 // Lane zero of the following bias group is requested on a fused seed.
 wire prefetch_req=fused_seed || (state==MAC && k>=KPAR && k<=COLS*KPAR);
 wire capture_bias=(state==MAC || state==LAST) && k>=2*KPAR && k<=(COLS+1)*KPAR;
 wire [2:0] prefetch_lane=fused_seed ? 0 : (k>>$clog2(KPAR))-1;
 wire [7:0] next_col=group_last ? 0 : col+COLS;
 wire [7:0] bias_prefetch_col=fused_seed ? next_col+COLS : next_col;
 wire [7:0] ba=bwrite ? dma_load_addr[9:2] : prefetch_req ? bias_prefetch_col+prefetch_lane : col+bias_lane;
 wire [15:0] bl,bh;wire [15:0] xq[0:1][0:ROWS-1][0:1];wire [15:0] wq[0:COLS-1][0:1];
 wire signed [39:0] acc[0:ROWS-1][0:COLS-1];
 genvar t,r,c,p,d;
 generate
 // Each tile/row/parity uses a native 128-word SRAM; no full X flop array.
 for(t=0;t<2;t=t+1)begin:tiles
 for(r=0;r<ROWS;r=r+1)begin:rows
 for(p=0;p<2;p=p+1)begin:parity
 wire wr=xwrite && load_tile==t && (load_row&(ROWS-1))==r;
 kwt_sram16 #(.AW(7)) xm(.clk(clk),.cs(wr || (read_operands && (((operand_row>>RL)&1)==t))),.we(wr),
 .addr(wr ? {2'b0,dma_load_addr[7:3]} : {2'b0,operand_k[5:1]}),.din(dma_load_data[16*p+:16]),.dout(xq[t][r][p]));
 end end end
 for(c=0;c<COLS;c=c+1)begin:columns
 for(p=0;p<2;p=p+1)begin:parity
 // Both k parities are stored even when the PE consumes one k per cycle.
 if(COLS==8)begin:depth1
 wire wr=wwrite && dma_load_addr[10:8]==c;
 kwt_sram16 #(.AW(10)) wm(.clk(clk),.cs(wr || read_operands),.we(wr),
 .addr(wr ? {dma_load_addr[15:11],dma_load_addr[7:3]} : {operand_col[7:3],operand_k[5:1]}),
 .din(dma_load_data[16*p+:16]),.dout(wq[c][p]));
 end else begin:depth2
 wire [15:0] q[0:1];reg sel;
 always @(posedge clk)if(read_operands)sel<=operand_col[7];
 for(d=0;d<2;d=d+1)begin:bank
 wire wr=wwrite && dma_load_addr[9:8]==c && dma_load_addr[15]==d;
 kwt_sram16 #(.AW(10)) wm(.clk(clk),.cs(wr || (read_operands && operand_col[7]==d)),.we(wr),
 .addr(wr ? {dma_load_addr[14:10],dma_load_addr[7:3]} : {operand_col[6:2],operand_k[5:1]}),
 .din(dma_load_data[16*p+:16]),.dout(q[d]));end
 assign wq[c][p]=q[sel];end end
 for(r=0;r<ROWS;r=r+1)begin:pes
 wire [15:0] xx0=(KPAR==1 && operand_parity) ? xq[read_tile][r][1] : xq[read_tile][r][0];
 wire [15:0] ww0=(KPAR==1 && operand_parity) ? wq[c][1] : wq[c][0];
 kwt_tile_mac #(.KPAR(KPAR),.PRODUCT_PIPE(PRODUCT_PIPE)) pe(.clk(clk),.rst_n(rst_n),.clear(dma_clear || start),
 .valid(product_valid),.first(first || fused_seed),.bias(bias[c]),
 .x0(xx0),.w0(ww0),
 .x1(xq[read_tile][r][1]),.w1(wq[c][1]),.acc(acc[r][c]));end end
 if(SMALL_BIAS)begin:compact
 wire [15:0] q[0:1][0:1];reg sel;
 always @(posedge clk)if(state==BREQ || prefetch_req)sel<=ba[7];
 for(d=0;d<2;d=d+1)begin:depth
 for(p=0;p<2;p=p+1)begin:halfword
 kwt_sram16 #(.AW(7)) bm(.clk(clk),.cs((bwrite || state==BREQ || prefetch_req) && ba[7]==d),.we(bwrite),
 .addr(ba[6:0]),.din(dma_load_data[16*p+:16]),.dout(q[d][p]));end end
 assign bl=q[sel][0];assign bh=q[sel][1];
 end else begin:full_bias
 kwt_sram16 #(.AW(10)) lo(.clk(clk),.cs(bwrite || state==BREQ || prefetch_req),.we(bwrite),.addr({2'b0,ba}),.din(dma_load_data[15:0]),.dout(bl));
 kwt_sram16 #(.AW(10)) hi(.clk(clk),.cs(bwrite || state==BREQ || prefetch_req),.we(bwrite),.addr({2'b0,ba}),.din(dma_load_data[31:16]),.dout(bh));end
 endgenerate
 assign dma_x_free=~x_valid;assign dma_out_valid=count!=0;assign dma_out_index=indices[head];
 assign dma_out_data={{24{fifo[head][39]}},fifo[head]};assign dma_done=done;assign dma_fault=fault;
 assign perf_cycles=cycles;assign perf_mac_cycles=mac_cycles;assign perf_fifo_wait=fifo_wait;
 integer ri,ci;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin
 state<=IDLE;row<=0;col<=0;k<=0;x_valid<=0;nx<=0;nw<=0;nb<=0;
 bias_lane<=0;return_lane<=0;first<=0;operand_parity<=0;read_tile<=0;prefetched<=0;
 head<=0;tail<=0;count<=0;popped<=0;done<=0;fault<=0;cycles<=0;mac_cycles<=0;fifo_wait<=0;
 end else begin
 if(busy)cycles<=cycles+1;
 if(product_valid)begin mac_cycles<=mac_cycles+1;first<=0;end
 if(state==EMIT && !push)fifo_wait<=fifo_wait+1;
 if((load && !(xwrite || wwrite || bwrite)) || (dma_start && !start))fault<=1;
 if(read_operands)begin operand_parity<=operand_k[0];read_tile<=(operand_row>>RL)&1;end
 if(state==LAST)prefetched<=early_read;
 if(state==PIPE && early_read)prefetched<=1;
 if(xwrite)begin nx<=nx+1;
 if(dma_load_addr[7:3]==31 && ((load_row&(ROWS-1))==ROWS-1 || load_row==98))x_valid[load_tile]<=1;end
 if(wwrite)nw<=nw+1;if(bwrite)nb<=nb+1;
 if(state==BREQ)state<=BLOAD;
 if(state==BLOAD)begin bias[bias_lane]<={bh,bl};bias_lane<=bias_lane+1;
 if(bias_lane==COLS-1)begin state<=PRIME;k<=0;end else state<=BREQ;end
 if(prefetch_req)return_lane<=prefetch_lane;
 if(capture_bias)bias[return_lane]<={bh,bl};
 if(state==PRIME)begin state<=MAC;k<=KPAR;first<=1;end
 if(state==MAC)begin k<=k+KPAR;if(k==64-KPAR)state<=LAST;end
 if(state==LAST)state<=PRODUCT_PIPE ? PIPE : EMIT;
 if(state==PIPE)state<=EMIT;
 if(state==WAIT_TILE && x_valid[tile_bank])begin state<=PRIME;k<=0;end
 case({push,pop})
 2'b10:count<=count+batch;2'b01:count<=count-1;2'b11:count<=count+batch-1;default:begin end endcase
 if(push)begin
 for(ri=0;ri<ROWS;ri=ri+1)for(ci=0;ci<COLS;ci=ci+1)if(row+ri<99)begin
 fifo[6'(tail+(ri<<CL)+ci)]<=acc[ri][ci];indices[6'(tail+(ri<<CL)+ci)]<=((row+ri)<<8)+col+ci;end
 tail<=tail+batch;if(group_last)x_valid[tile_bank]<=0;
 if(final_group)state<=DRAIN;
 else begin
 if(group_last)begin row<=row+ROWS;col<=0;end else col<=col+COLS;
 k<=prime_next ? (fused_seed ? 2*KPAR : KPAR) : 0;first<=!fused_seed;prefetched<=0;state<=prime_next ? MAC : PRIME;
 if(group_last && !next_tile_valid)state<=WAIT_TILE;end end
 if(pop)begin head<=head+1;popped<=popped+1;if(popped==25343)begin state<=IDLE;done<=1;end end
 if(start)begin state<=BREQ;row<=0;col<=0;k<=0;bias_lane<=0;first<=0;
 done<=0;head<=0;tail<=0;count<=0;popped<=0;cycles<=0;mac_cycles<=0;fifo_wait<=0;end
 if(dma_clear)begin state<=IDLE;row<=0;col<=0;k<=0;x_valid<=0;nx<=0;nw<=0;nb<=0;
 bias_lane<=0;return_lane<=0;first<=0;prefetched<=0;head<=0;tail<=0;count<=0;popped<=0;
 done<=0;fault<=0;cycles<=0;mac_cycles<=0;fifo_wait<=0;end
 end end
endmodule




