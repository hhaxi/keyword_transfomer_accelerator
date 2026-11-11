// Output-stationary 8x8 tile, two K products per lane per cycle.
module kwt_tile_core #(parameter ROWS=8,COLS=8,KPAR=2,FUSE=0,PRODUCT_PIPE=0,SMALL_BIAS=0,TAIL_FIRST=0,X_DELTA=0)(
 input wire clk,rst_n,input wire dma_load_valid,input wire [19:0] dma_load_addr,
 input wire [31:0] dma_load_data,output wire dma_load_ready,
 input wire dma_w_valid,input wire [63:0] dma_w_quad,input wire [11:0] dma_w_index,
 output wire dma_w_ready,
 input wire dma_x_valid,input wire [67:0] dma_x_residual,input wire [10:0] dma_x_index,
 output wire dma_x_ready,
 input wire dma_start,dma_clear,output wire [1:0] dma_x_free,
 output wire dma_out_valid,output wire [63:0] dma_out_data,
 output wire [14:0] dma_out_index,input wire dma_out_ready,
 output wire dma_done,dma_fault,output wire [31:0] perf_cycles,perf_mac_cycles,perf_fifo_wait);
 generate if(ROWS!=8 || COLS!=8 || KPAR!=2)begin:unsupported
  KWT_Q128_REQUIRED invalid_geometry();
 end endgenerate
 localparam RL=$clog2(ROWS),CL=$clog2(COLS);
 localparam IDLE=0,BREQ=1,BLOAD=2,PRIME=3,MAC=4,LAST=5,PIPE=6,EMIT=7,WAIT_TILE=8,DRAIN=9;
 reg [3:0] state;reg [6:0] row;reg [7:0] col;reg [6:0] k;
 reg [1:0] x_valid;reg [11:0] nx;reg [12:0] nw;reg [8:0] nb;
 reg [3:0] tile_seq;
 reg [10:0] nqx,x_pending_index;
 reg [67:0] x_pending_residual;
 reg x_pending;
 wire [15:0] xq[0:1][0:ROWS-1][0:1];
 reg [CL-1:0] bias_lane,return_lane;reg [31:0] bias[0:COLS-1];reg first,read_tile,prefetched;
 wire queue_ready,queue_valid;wire [31:0] queue_word;wire [14:0] queue_index;reg [14:0] popped;reg done,fault;reg [31:0] cycles,mac_cycles,fifo_wait;
 wire busy=state!=IDLE;wire [6:0] load_row=dma_load_addr[14:8];wire load_tile=(load_row>>RL)&1;
 wire xspace=dma_load_addr>=20'h10000 && dma_load_addr<20'h16300;
 assign dma_load_ready=xspace ? !x_valid[load_tile] : !busy;
 wire load=dma_load_valid && dma_load_ready;
 wire [11:0] raw_rest=nx-12'd96;
 wire [11:0] raw_index=TAIL_FIRST ? (nx<96 ? 12'd3072+nx : {raw_rest[11:8]^4'd1,raw_rest[7:0]}) : nx;
 wire xwrite=!X_DELTA && load && xspace && dma_load_addr[2:0]==0 && dma_load_addr[14:3]==raw_index && nx<3168;
 wire [10:0] x_rest=nqx-11'd64;
 wire [10:0] expected_x_index=TAIL_FIRST ? (nqx<64 ? 11'd1536+nqx : {x_rest[10:7]^4'd1,x_rest[6:0]}) : nqx;
 wire x_index_ok=dma_x_index==expected_x_index;
 wire [2:0] x_even_row={dma_x_index[6:5],1'b0};
 wire [2:0] x_pred_row=x_even_row-3'd1;
 wire [2:0] x_pending_row={x_pending_index[6:5],1'b0};
 wire x_conflict=x_pending && x_even_row!=0 && dma_x_index[7]==x_pending_index[7] &&
                (x_pred_row==x_pending_row || x_pred_row==x_pending_row+3'd1);
 wire [15:0] x_base0=x_pending_row==0 ? 16'd0 : xq[x_pending_index[7]][x_pending_row-3'd1][0];
 wire [15:0] x_base1=x_pending_row==0 ? 16'd0 : xq[x_pending_index[7]][x_pending_row-3'd1][1];
 wire signed [18:0] x_even0=$signed({{3{x_base0[15]}},x_base0})+$signed({{2{x_pending_residual[16]}},x_pending_residual[16:0]});
 wire signed [18:0] x_even1=$signed({{3{x_base1[15]}},x_base1})+$signed({{2{x_pending_residual[33]}},x_pending_residual[33:17]});
 wire signed [18:0] x_odd0=x_even0+$signed({{2{x_pending_residual[50]}},x_pending_residual[50:34]});
 wire signed [18:0] x_odd1=x_even1+$signed({{2{x_pending_residual[67]}},x_pending_residual[67:51]});
 wire x_tail_row=x_pending_index[10:5]==6'd49;
 wire x_overflow=x_even0 < -19'sd32768 || x_even0 > 19'sd32767 ||
                 x_even1 < -19'sd32768 || x_even1 > 19'sd32767 ||
                 (!x_tail_row && (x_odd0 < -19'sd32768 || x_odd0 > 19'sd32767 ||
                                  x_odd1 < -19'sd32768 || x_odd1 > 19'sd32767));
 assign dma_x_ready=X_DELTA && rst_n && !dma_clear && !fault && nqx<1600 &&
                    !x_valid[expected_x_index[7]] && (!x_index_ok || !x_conflict) && !(x_pending && x_overflow);
 wire x_accept=dma_x_valid && dma_x_ready;
 wire x_bad_index=x_accept && !x_index_ok;
 wire x_predict=x_accept && x_index_ok && x_even_row!=0;
 wire x_commit=x_pending && rst_n && !dma_clear && !fault && !x_overflow && !x_bad_index;
 wire [15:0] x_restored[0:3];
 assign x_restored[0]=x_even0[15:0];assign x_restored[1]=x_even1[15:0];
 assign x_restored[2]=x_odd0[15:0];assign x_restored[3]=x_odd1[15:0];
 // W has a dedicated two-column port; the address-driven port carries X/B.
 assign dma_w_ready=rst_n && !dma_clear && !busy && !fault && nw<4096;
 wire wload=dma_w_valid && dma_w_ready;
 wire wwrite=wload && dma_w_index==nw[11:0];
 wire bwrite=load && dma_load_addr>=20'h30000 && dma_load_addr<20'h30400 && dma_load_addr[1:0]==0 && dma_load_addr[9:2]==nb[7:0] && nb<256;
 wire complete_load=x_valid[0] && nw==4096 && nb==256;
 wire start=dma_start && !busy && complete_load;
 wire pop=queue_valid && dma_out_ready;
 wire [RL:0] valid_rows=(row+ROWS>99) ? (RL+1)'(99-row) : (RL+1)'(ROWS);
 wire push=state==EMIT && queue_ready;
 wire group_last=col==256-COLS;
 wire final_group=group_last && tile_seq==12;
 function [3:0] physical_tile;
 input [3:0] seq;
 begin physical_tile=TAIL_FIRST ? (seq==0 ? 4'd12 : ((seq-1'b1)^4'd1)) : seq;end
 endfunction
 wire [6:0] next_row_base={physical_tile(tile_seq+1'b1),3'b0};
 wire tile_bank=(row>>RL)&1;wire next_tile_valid=x_valid[!tile_bank];
 wire next_available=!final_group && (!group_last || next_tile_valid);
 // SRAM request at LAST/PIPE returns before EMIT. Fused EMIT commits old acc
 // and seeds the next group on the same edge, including registered products.
 wire early_read=FUSE && (state==LAST || state==PIPE) && next_available;
 wire fused_seed=FUSE && push && prefetched && next_available;
 wire prime_next=push && next_available;
 wire next_address=early_read || prime_next;
 wire [6:0] operand_row=(next_address && group_last) ? next_row_base : row;
 wire [7:0] operand_col=next_address ? (group_last ? 0 : col+COLS) : col;
 wire [6:0] operand_k=next_address ? (fused_seed ? KPAR : 0) : k;
 wire read_operands=state==PRIME || state==MAC || next_address;
 wire product_valid=state==MAC || state==LAST || fused_seed;
 // Lane zero of the following bias group is requested on a fused seed.
 wire prefetch_req=fused_seed || (state==MAC && k>=KPAR && k<=COLS*KPAR);
 wire capture_bias=(state==MAC || state==LAST) && k>=2*KPAR && k<=(COLS+1)*KPAR;
 wire [CL-1:0] prefetch_lane=fused_seed ? 0 : CL'(k>>$clog2(KPAR))-1'b1;
 wire [7:0] next_col=group_last ? 0 : col+COLS;
 wire [7:0] bias_prefetch_col=fused_seed ? next_col+COLS : next_col;
 wire [7:0] ba=bwrite ? dma_load_addr[9:2] : prefetch_req ? bias_prefetch_col+prefetch_lane : col+bias_lane;
 wire [15:0] bl,bh;wire [15:0] wq[0:COLS-1][0:1];
 wire [15:0] compute_x[0:ROWS-1][0:1];
 wire signed [39:0] acc[0:ROWS-1][0:COLS-1];
 genvar t,r,c,p,d;
 generate
 // One isolated X pair per row is shared by all eight column lanes.
 for(r=0;r<ROWS;r=r+1)begin:isolate_rows
  assign compute_x[r][0]=product_valid ? xq[read_tile][r][0] : 16'b0;
  assign compute_x[r][1]=product_valid ? xq[read_tile][r][1] : 16'b0;
 end
 // Each tile/row/parity uses a native 128-word SRAM; no full X flop array.
 for(t=0;t<2;t=t+1)begin:tiles
 for(r=0;r<ROWS;r=r+1)begin:rows
 for(p=0;p<2;p=p+1)begin:parity
 wire raw_wr=xwrite && load_tile==t && (load_row&(ROWS-1))==r;
 wire delta_wr=x_commit && x_pending_index[7]==t &&
               (x_pending_row==r || (!x_tail_row && x_pending_row+3'd1==r));
 wire wr=raw_wr || delta_wr;
 wire pred_read=x_predict && dma_x_index[7]==t && x_pred_row==r;
 wire compute_read=read_operands && (((operand_row>>RL)&1)==t);
 // The predecessor request and pending write are allowed together only when
 // they touch different physical macros. Row-pair boundaries stall one cycle.
 kwt_sram16 #(.AW(7),.GATE_CLK(1)) xm(.clk(clk),.cs(wr || pred_read || compute_read),.we(wr),
 .addr(raw_wr ? {2'b0,dma_load_addr[7:3]} : delta_wr ? {2'b0,x_pending_index[4:0]} :
       pred_read ? {2'b0,dma_x_index[4:0]} : {2'b0,operand_k[5:1]}),
 .din(delta_wr ? x_restored[(r%2)*2+p] : dma_load_data[16*p+:16]),.dout(xq[t][r][p]));
 end end end
 for(c=0;c<COLS;c=c+1)begin:columns
 for(p=0;p<2;p=p+1)begin:parity
 // One bank per column lane and K parity. All 1024 entries are used.
 // An adjacent-column quad writes four distinct existing SRAMs. The
 // upper q bits select the column group; low five bits select the K pair.
 wire wr=wwrite && dma_w_index[6:5]==(c/2);
 kwt_sram16 #(.AW(10),.GATE_CLK(1)) wm(.clk(clk),.cs(wr || read_operands),.we(wr),
 .addr(wr ? {dma_w_index[11:7],dma_w_index[4:0]} : {operand_col[7:3],operand_k[5:1]}),
 .din(dma_w_quad[(c%2)*32+16*p+:16]),.dout(wq[c][p]));
 end
 for(r=0;r<ROWS;r=r+1)begin:pes
 kwt_tile_mac #(.KPAR(KPAR),.PRODUCT_PIPE(PRODUCT_PIPE)) pe(.clk(clk),.rst_n(rst_n),.clear(dma_clear || start),
 .valid(product_valid),.first(first || fused_seed),.bias(bias[c]),
 .x0(compute_x[r][0]),.w0(wq[c][0]),
 .x1(compute_x[r][1]),.w1(wq[c][1]),.acc(acc[r][c]));end end
 if(SMALL_BIAS)begin:compact
 wire [15:0] q[0:1][0:1];reg sel;
 always @(posedge clk)if(state==BREQ || prefetch_req)sel<=ba[7];
 for(d=0;d<2;d=d+1)begin:depth
 for(p=0;p<2;p=p+1)begin:halfword
 kwt_sram16 #(.AW(7),.GATE_CLK(1)) bm(.clk(clk),.cs((bwrite || state==BREQ || prefetch_req) && ba[7]==d),.we(bwrite),
 .addr(ba[6:0]),.din(dma_load_data[16*p+:16]),.dout(q[d][p]));end end
 assign bl=q[sel][0];assign bh=q[sel][1];
 end else begin:full_bias
 kwt_sram16 #(.AW(10),.GATE_CLK(1)) lo(.clk(clk),.cs(bwrite || state==BREQ || prefetch_req),.we(bwrite),.addr({2'b0,ba}),.din(dma_load_data[15:0]),.dout(bl));
 kwt_sram16 #(.AW(10),.GATE_CLK(1)) hi(.clk(clk),.cs(bwrite || state==BREQ || prefetch_req),.we(bwrite),.addr({2'b0,ba}),.din(dma_load_data[31:16]),.dout(bh));end
 endgenerate
 wire [2559:0] group_values;
 genvar qr,qc;
 generate for(qr=0;qr<ROWS;qr=qr+1)begin:queue_rows
 for(qc=0;qc<COLS;qc=qc+1)begin:queue_columns
   assign group_values[(qr*COLS+qc)*40+:40]=acc[qr][qc];
 end end endgenerate
 kwt_int16_result_queue #(.ROWS(ROWS),.COLS(COLS)) result_queue(.clk(clk),.rst_n(rst_n),
   .clear(dma_clear || start),.in_valid(state==EMIT),.in_ready(queue_ready),.in_values(group_values),
   .in_row(row),.in_col(col),.in_rows(valid_rows),
   .out_valid(queue_valid),.out_ready(dma_out_ready),.out_word(queue_word),.out_index(queue_index));
 assign dma_x_free=~x_valid;assign dma_out_valid=queue_valid;assign dma_out_index=queue_index;
 assign dma_out_data={32'b0,queue_word};assign dma_done=done;assign dma_fault=fault;
 assign perf_cycles=cycles;assign perf_mac_cycles=mac_cycles;assign perf_fifo_wait=fifo_wait;
 integer ri,ci;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin
 state<=IDLE;row<=0;col<=0;k<=0;x_valid<=0;nx<=0;nw<=0;nb<=0;
 tile_seq<=0;nqx<=0;x_pending<=0;x_pending_index<=0;x_pending_residual<=0;
 bias_lane<=0;return_lane<=0;first<=0;read_tile<=0;prefetched<=0;
 popped<=0;done<=0;fault<=0;cycles<=0;mac_cycles<=0;fifo_wait<=0;
 end else begin
 if(busy)cycles<=cycles+1;
 if(product_valid)begin mac_cycles<=mac_cycles+1;first<=0;end
 if(state==EMIT && !push)fifo_wait<=fifo_wait+1;
 if((load && !(xwrite || bwrite)) || (wload && !wwrite) || (dma_start && !start))fault<=1;
 if(x_bad_index || (x_pending && x_overflow))fault<=1;
 x_pending<=x_accept && x_index_ok;
 if(x_accept && x_index_ok)begin
   nqx<=nqx+1'b1;x_pending_index<=dma_x_index;x_pending_residual<=dma_x_residual;
 end
 if(x_commit)begin
   nx<=nx+(x_tail_row ? 12'd1 : 12'd2);
   if((x_pending_index[10:7]==12 && x_pending_index[6:0]==63) || x_pending_index[6:0]==127)
     x_valid[x_pending_index[7]]<=1;
 end
 if(read_operands)read_tile<=(operand_row>>RL)&1;
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
 if(push)begin
 if(group_last)x_valid[tile_bank]<=0;
 if(final_group)state<=DRAIN;
 else begin
 if(group_last)begin row<=next_row_base;tile_seq<=tile_seq+1'b1;col<=0;end else col<=col+COLS;
 k<=prime_next ? (fused_seed ? 2*KPAR : KPAR) : 0;first<=!fused_seed;prefetched<=0;state<=prime_next ? MAC : PRIME;
 if(group_last && !next_tile_valid)state<=WAIT_TILE;end end
 if(pop)begin popped<=popped+1;if(popped==12671)begin state<=IDLE;done<=1;end end
 if(start)begin state<=BREQ;row<=TAIL_FIRST ? 7'd96 : 7'd0;tile_seq<=0;col<=0;k<=0;bias_lane<=0;first<=0;
 done<=0;popped<=0;cycles<=0;mac_cycles<=0;fifo_wait<=0;end
 if(dma_clear)begin state<=IDLE;row<=0;col<=0;k<=0;x_valid<=0;nx<=0;nw<=0;nb<=0;
 tile_seq<=0;nqx<=0;x_pending<=0;x_pending_index<=0;x_pending_residual<=0;
 bias_lane<=0;return_lane<=0;first<=0;prefetched<=0;popped<=0;
 done<=0;fault<=0;cycles<=0;mac_cycles<=0;fifo_wait<=0;end
 end end
endmodule




