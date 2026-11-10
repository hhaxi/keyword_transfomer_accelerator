`timescale 1ns/1ps
`include "kwt_optional.vh"
module kwt_tile_core #(parameter ROWS=8,COLS=8,KPAR=2,FUSE=1,PRODUCT_PIPE=0,SMALL_BIAS=1,X_DELTA=0,TAIL_FIRST=0)(
 input wire clk,rst_n,dma_load_valid,input wire [19:0]dma_load_addr,input wire [31:0]dma_load_data,output wire dma_load_ready,
 input wire dma_w_valid,output wire dma_w_ready,input wire [63:0]dma_w_quad,input wire [11:0]dma_w_index,
 input wire dma_x_valid,output wire dma_x_ready,input wire [67:0]dma_x_residual,input wire [10:0]dma_x_index,
 input wire dma_start,dma_clear,output wire [1:0]dma_x_free,output wire dma_out_valid,output wire [63:0]dma_out_data,
 output wire [14:0]dma_out_index,input wire dma_out_ready,output wire dma_done,dma_fault,output wire [31:0]perf_cycles,perf_mac_cycles,perf_fifo_wait);
 reg hold_w=0,hold_x=0;integer edges=0,nw=0,nb=0,nx=0,nqx=0;
 reg [1:0]vx=0;reg busy=0,done=0;integer seq=0,wi=0,warmup=0;
 function integer tile_id(input integer s);tile_id=`KWT_TAIL_FIRST ? (s==0?12:((s-1)^1)):s;endfunction
 function integer qtag(input integer n);integer z;begin z=n-64;qtag=!`KWT_TAIL_FIRST?n:n<64?1536+n:((((z>>7)^1)<<7)|(z&127));end endfunction
 function integer rawtag(input integer n);integer z;begin z=n-96;rawtag=!`KWT_TAIL_FIRST?n:n<96?3072+n:((((z>>8)^1)<<8)|(z&255));end endfunction
 wire [3:0]tid=4'(tile_id(seq));wire bank=tid[0];wire [10:0]words=tid==12?384:1024;
 assign dma_load_ready=1;assign dma_w_ready=!hold_w && edges%7!=0;
 assign dma_x_ready=!hold_x && edges%7!=0 && !vx[dma_x_index[7]];assign dma_x_free=~vx;
 assign dma_out_valid=busy && vx[bank] && warmup==0;assign dma_out_index=15'(tid*1024+wi);
 assign dma_out_data={32'b0,(32'(dma_out_index)^32'h12345678)};
 assign dma_done=done;assign dma_fault=0;assign perf_cycles=0;assign perf_mac_cycles=0;assign perf_fifo_wait=0;
 always @(posedge clk)begin
  edges<=edges+1;
  if(!rst_n || dma_clear)begin nw<=0;nb<=0;nx<=0;nqx<=0;vx<=0;busy<=0;done<=0;seq<=0;wi<=0;warmup<=0;end else begin
   if(dma_load_valid && dma_load_ready)case(dma_load_addr[19:16])
    3:begin if(nw!=4096)$fatal(1,"bias before W complete");nb<=nb+1;end
    1:begin
     if(`KWT_X_DELTA)$fatal(1,"compressed X must use residual quad port");
     if(dma_load_addr[14:3]!==12'(rawtag(nx)))$fatal(1,"raw tail order mismatch");nx<=nx+1;
     if(dma_load_addr[7:3]==31 && (dma_load_addr[10:8]==7 || dma_load_addr[14:8]==98))vx[dma_load_addr[11]]<=1;
    end
    default:$fatal(1,"bad local load");endcase
   if(dma_w_valid && dma_w_ready)begin
    if(dma_w_index!==12'(nw) || dma_w_quad!==64'h0000ffff0000ffff)$fatal(1,"bad W quad");nw<=nw+1;end
   if(dma_x_valid && dma_x_ready)begin
    if(!`KWT_X_DELTA || nb!=256 || dma_x_residual!==0 || dma_x_index!==11'(qtag(nqx)))$fatal(1,"bad X quad n=%0d tag=%0d",nqx,dma_x_index);
    nqx<=nqx+1;nx<=nx+(dma_x_index[10:5]==49?1:2);
    if(dma_x_index[4:0]==31 && (dma_x_index[6:5]==3 || dma_x_index[10:5]==49))vx[dma_x_index[7]]<=1;
   end
   if(dma_start)begin if(nw!=4096 || nb!=256 || !vx[0])$fatal(1,"early launch");busy<=1;done<=0;seq<=0;wi<=0;warmup<=12;end
   if(warmup!=0)warmup<=warmup-1;
   if(dma_out_valid && dma_out_ready)begin
    if(wi==words-1)begin vx[bank]<=0;wi<=0;warmup<=12;if(seq==12)begin busy<=0;done<=1;end else seq<=seq+1;end
    else wi<=wi+1;
   end
  end
 end
endmodule
module tb_dma_compressed;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,cv=0,cr=0;reg [19:0]ca=0;reg [31:0]cd=0;
 wire cy,rv,re,mv,mr,mrr,mrv,merr,irq;wire [31:0]rd,ma,md,mrd;wire [3:0]mm;reg mready=0,inject_error=0;
 kwt_ffn1_dma dut(.clk(clk),.rst_n(rst_n),.cmd_valid(cv),.cmd_ready(cy),.cmd_addr(ca),.cmd_read(cr),.cmd_wdata(cd),.cmd_wmask(4'hf),
 .rsp_valid(rv),.rsp_ready(1'b1),.rsp_rdata(rd),.rsp_err(re),.m_valid(mv),.m_ready(mready),.m_addr(ma),.m_wdata(md),.m_read(mr),.m_mask(mm),
 .m_rsp_valid(mrv),.m_rsp_ready(mrr),.m_rdata(mrd),.m_err(merr),.irq_event(irq));
 reg [31:0]qa[0:3];integer head=0,tail=0,qn=0,ticks=0,width=16;reg offering=0;
 wire push=mv&&mready,pop=mrv&&mrr;reg [12671:0]seen=0;integer writes=0,yi;
 assign mrv=offering && qn!=0;assign merr=inject_error;
 function [31:0]data(input [31:0]a);integer i,idx;reg [31:0]z;begin z=0;
  if(a>=32'ha0020000 && a<32'ha0028080)begin idx=(a-32'ha0020000)/4;
   if(idx<32)for(i=0;i<8;i=i+1)z=z|((width-1)<<(i*4));
   else for(i=0;i<32;i=i+1)if((((idx-32)*32+i)%(2*width))<width)z[i]=1;end
  if(`KWT_X_DELTA && a==32'ha001003c)z=32'h58440000|(`KWT_TAIL_FIRST?32'h8000:0);data=z;end endfunction
 assign mrd=data(qa[head]);
 always @(posedge clk)if(!rst_n)begin head<=0;tail<=0;qn<=0;ticks<=0;offering<=0;mready<=0;end else begin
  ticks<=ticks+1;mready<=qn<2 && ticks%5!=0;if(mrv&&!mrr)offering<=1;else offering<=qn!=0 && ticks%4!=0;
  if(push)begin qa[tail]<=ma;tail<=(tail+1)%4;if(!mr)begin yi=(ma-32'ha0040000)/4;
   if(ma[1:0]!=0 || yi<0 || yi>=12672 || seen[yi] || md!==(32'(yi)^32'h12345678))$fatal(1,"bad Y addr=%h",ma);
   seen[yi]=1;writes=writes+1;end end
  if(pop)head<=(head+1)%4;case({push,pop})2:qn<=qn+1;1:qn<=qn-1;default:;endcase
  if(qn>2)$fatal(1,"credit overflow");end
 reg held=0;reg [68:0]offer;
 always @(posedge clk)if(!rst_n)held<=0;else begin if(held && (!mv || {ma,md,mr,mm}!==offer))$fatal(1,"unstable request");held<=mv&&!mready;offer<={ma,md,mr,mm};end
 task csr(input [19:0]a,input [31:0]d);begin @(negedge clk);cv=1;ca=a;cd=d;wait(cy);@(posedge clk);@(negedge clk);cv=0;if(re)$fatal(1,"CSR error");end endtask
 task start_task;begin seen=0;writes=0;csr(20'h20,32'ha0010000);csr(20'h24,32'ha0020000);csr(20'h28,32'ha0030000);csr(20'h2c,32'ha0040000);csr(0,1);end endtask
 task stop_task;begin csr(0,2);wait(dut.phase==0 && qn==0 && !dut.req_valid);repeat(3)@(posedge clk);end endtask
 task full_task(input integer w);begin width=w;start_task();wait(dut.done && dut.phase==0 && qn==0);
  if(writes!=12672 || !(&seen) || dut.tile_engine.core.nx!=3168 || dut.tile_engine.core.nw!=4096 || dut.error)$fatal(1,"incomplete task");
  if(`KWT_X_DELTA && dut.tile_engine.core.nqx!=1600)$fatal(1,"incomplete X");stop_task();end endtask
 initial begin repeat(4)@(negedge clk);rst_n=1;
  start_task();wait(dut.tile_engine.core.nw>=300);@(negedge clk);dut.tile_engine.core.hold_w=1;wait(mrv&&!mrr);stop_task();@(negedge clk);dut.tile_engine.core.hold_w=0;
  if(`KWT_X_DELTA)begin
   width=10;start_task();wait(dut.tile_engine.core.nb==256);@(negedge clk);dut.tile_engine.core.hold_x=1;wait(mrv&&!mrr);stop_task();@(negedge clk);dut.tile_engine.core.hold_x=0;
   start_task();wait(dut.tile_engine.core.nb==256);@(negedge clk);dut.tile_engine.core.hold_x=1;wait(mrv&&!mrr);@(negedge clk);inject_error=1;wait(dut.phase==0 && qn==0);
   @(negedge clk);inject_error=0;dut.tile_engine.core.hold_x=0;if(!dut.error)$fatal(1,"X error drain failed");end
  full_task(1);full_task(10);full_task(16);
  $display("DMA_XDELTA_TAIL_PASS widths=1,10,16 abort_restart=1 error_restart=1 outputs=38016 x_delta=%0d tail_first=%0d",`KWT_X_DELTA,`KWT_TAIL_FIRST);$finish;end
 initial begin #20000000;$fatal(1,"timeout phase=%0d",dut.phase);end
endmodule
