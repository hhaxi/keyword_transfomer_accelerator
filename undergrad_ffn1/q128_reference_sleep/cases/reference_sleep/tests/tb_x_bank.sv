`timescale 1ns/1ps
`ifndef CORE
`define CORE dut
`endif
module tb_x_bank #(parameter TAIL_FIRST=0);
 reg clk=0,rst_n=0,dma_clear=0;
 always #5 clk=~clk;
 reg dma_x_valid=0;
 reg [67:0] dma_x_residual=0;
 reg [10:0] dma_x_index=0;
 wire dma_x_ready,dma_fault;
 wire [1:0] dma_x_free;
 wire dma_load_ready,dma_w_ready,dma_out_valid,dma_done;
 wire [63:0] dma_out_data;
 wire [14:0] dma_out_index;
 wire [31:0] perf_cycles,perf_mac_cycles,perf_fifo_wait;
 reg dma_load_valid=0;
 reg [19:0] dma_load_addr=0;
 kwt_tile_core #(.X_DELTA(1),.TAIL_FIRST(TAIL_FIRST),.FUSE(1),.SMALL_BIAS(1)) dut(
 .clk(clk),.rst_n(rst_n),.dma_clear(dma_clear),.dma_start(1'b0),
 .dma_load_valid(dma_load_valid),.dma_load_addr(dma_load_addr),.dma_load_data(32'b0),.dma_load_ready(dma_load_ready),
 .dma_w_valid(1'b0),.dma_w_quad(64'b0),.dma_w_index(12'b0),.dma_w_ready(dma_w_ready),
 .dma_x_valid(dma_x_valid),.dma_x_residual(dma_x_residual),.dma_x_index(dma_x_index),.dma_x_ready(dma_x_ready),
 .dma_x_free(dma_x_free),.dma_out_valid(dma_out_valid),.dma_out_data(dma_out_data),
 .dma_out_index(dma_out_index),.dma_out_ready(1'b0),.dma_done(dma_done),.dma_fault(dma_fault),
 .perf_cycles(perf_cycles),.perf_mac_cycles(perf_mac_cycles),.perf_fifo_wait(perf_fifo_wait));
 reg [67:0] quads[0:1599];
 reg [10:0] tags[0:1599];
 reg [15:0] values[0:6335];
 string prefix,test_name;
 reg check_map=0,prior=0,forbid_writes=0,scan=0;
 reg [10:0] prior_tag;
 integer current_tile=0,scan_count=0,writes=0,reads=0,bubbles=0,full_bubbles=0,n,i;
 wire [6:0] input_row={dma_x_index[10:5],1'b0};
 wire [6:0] prior_row={prior_tag[10:5],1'b0};
 wire need_pred=input_row[2:0]!=0;
 genvar t,r,p;
 generate for(t=0;t<2;t=t+1)begin:tiles
 for(r=0;r<8;r=r+1)begin:rows
 for(p=0;p<2;p=p+1)begin:parities
   integer addr,physical_row;
   wire wr=`CORE.tiles[t].rows[r].parity[p].xm.we;
   wire cs=`CORE.tiles[t].rows[r].parity[p].xm.cs;
   wire want_write=prior && prior_tag[7]==t && (r==prior_row[2:0] || (prior_row!=98 && r==prior_row[2:0]+1));
   wire want_read=dma_x_valid && dma_x_ready && need_pred && dma_x_index[7]==t && r==input_row[2:0]-1;
   always @(posedge clk)begin
     if(rst_n && !dma_clear && `CORE.read_operands && (((`CORE.operand_row>>3)&1)==t) && (wr || want_read))
       $fatal(1,"X compute/preload single-port collision tile=%0d row=%0d parity=%0d",t,r,p);
     if(forbid_writes && wr)$fatal(1,"X wrote during reset/clear/fault");
     if(check_map)begin
       if(wr!==want_write)$fatal(1,"X write mapping tag=%0d tile=%0d row=%0d parity=%0d expected=%0d got=%0d",prior_tag,t,r,p,want_write,wr);
       if(want_write && want_read)$fatal(1,"single-port X read/write collision");
       if(cs!==(want_write || want_read))$fatal(1,"unexpected X bank access tile=%0d row=%0d",t,r);
       if(want_write)begin
         writes=writes+1;
         if(`CORE.tiles[t].rows[r].parity[p].xm.addr!=={2'b0,prior_tag[4:0]} ||
            `CORE.tiles[t].rows[r].parity[p].xm.din!==values[(prior_row+(r%2))*64+prior_tag[4:0]*2+p])
           $fatal(1,"X restored write mismatch tag=%0d bankrow=%0d parity=%0d",prior_tag,r,p);
       end
       if(want_read)begin
         reads=reads+1;
         if(wr || `CORE.tiles[t].rows[r].parity[p].xm.addr!=={2'b0,dma_x_index[4:0]})
           $fatal(1,"X predecessor request mismatch");
       end
     end
   end
   always @(posedge scan)begin
     physical_row=current_tile*8+r;
     if(current_tile%2==t && physical_row<99)for(addr=0;addr<32;addr=addr+1)begin
       if(`CORE.tiles[t].rows[r].parity[p].xm.native128.u_macro.model.mem[addr]!==values[physical_row*64+addr*2+p])
         $fatal(1,"X physical SRAM mismatch tile=%0d row=%0d parity=%0d address=%0d",current_tile,r,p,addr);
       scan_count=scan_count+1;
     end
   end
 end end end endgenerate
 task restart(input bit async_reset);
   @(negedge clk);dma_x_valid=0;check_map=0;prior=0;dma_load_valid=0;forbid_writes=1;
   if(async_reset)rst_n=0;else dma_clear=1;
   repeat(2)@(negedge clk);
   if(`CORE.nx!==0 || dma_x_free!==2'b11 || dma_fault)$fatal(1,"X restart retained state");
   rst_n=1;dma_clear=0;forbid_writes=0;
 endtask
 task drive(input integer index,input integer bad_index,input integer overflow);
   integer timeout;
   @(negedge clk);dma_x_valid=1;dma_x_index=tags[index]+bad_index;
   dma_x_residual=overflow==1 ? {17'd0,17'd0,17'd0,17'h10000} :
                  overflow>=2 ? (68'h0ffff<<((overflow-2)*17)) : quads[index];
   timeout=0;
   begin:accept
     while(timeout<20)begin
       @(posedge clk);
       if(dma_x_ready)begin
         #1;disable accept;
       end
       timeout=timeout+1;@(negedge clk);bubbles=bubbles+1;
     end
     $fatal(1,"X quad blocked index=%0d",index);
   end
 endtask
 // Monitor acceptance independently of internal pending implementation.
 always @(posedge clk)if(check_map)begin
   #0;
   prior<=dma_x_valid && dma_x_ready;
   if(dma_x_valid && dma_x_ready)prior_tag<=dma_x_index;
 end
 initial begin
   if(!$value$plusargs("PREFIX=%s",prefix))$fatal(1,"PREFIX missing");
   if(!$value$plusargs("NAME=%s",test_name))test_name="x";
   $readmemh({prefix,"_quads.hex"},quads);$readmemh({prefix,"_tags.hex"},tags);
   $readmemh({prefix,"_values.hex"},values);
   restart(1);check_map=1;
   for(n=0;n<1600;n=n+1)begin
     if(n==0 || tags[n][10:7]!=tags[n-1][10:7])begin
       @(negedge clk);`CORE.x_valid[tags[n][7]]=0;
     end
     drive(n,0,0);
     if(dma_x_free[tags[n][7]]!==1)$fatal(1,"X tile became valid before final quad commit");
     if((tags[n][10:7]==12 && tags[n][6:0]==63) || tags[n][6:0]==127)begin
       @(negedge clk);dma_x_valid=0;
       @(posedge clk);#1;
       if(dma_x_free[tags[n][7]]!==0)$fatal(1,"X tile not valid on final commit");
       @(negedge clk);prior=0;current_tile=tags[n][10:7];scan=1;#1;scan=0;
     end
   end
   if(`CORE.nx!==3168 || scan_count!=6336 || writes!=6336 || reads!=2368 || bubbles!=37)
     $fatal(1,"X coverage nx=%0d scans=%0d writes=%0d reads=%0d bubbles=%0d",`CORE.nx,scan_count,writes,reads,bubbles);
   full_bubbles=bubbles;
   // Concurrent compute requests target bank1 while restoration uses bank0.
   // PRIME keeps products inactive while exercising every SRAM read request.
   restart(0);
   force `CORE.state=3;force `CORE.row=8;force `CORE.x_valid=2'b10;
   for(i=0;i<34;i=i+1)drive(i,0,0);
   @(negedge clk);dma_x_valid=0;
   @(posedge clk);#1;
   if(dma_fault || `CORE.nx!==(TAIL_FIRST ? 66 : 68))$fatal(1,"concurrent X restore failed");
   release `CORE.state;release `CORE.row;release `CORE.x_valid;
   restart(0);
   // Occupied expected banks must hold the offer until the bank is released.
   @(negedge clk);`CORE.x_valid=2'b01;dma_x_valid=1;dma_x_index=tags[0];dma_x_residual=quads[0];
   repeat(4)begin @(posedge clk);#1;if(dma_x_ready || `CORE.nx!==0)$fatal(1,"occupied X bank accepted input");end
   restart(0);
   drive(0,1,0);@(negedge clk);dma_x_valid=0;
   @(posedge clk);#1;
   if(!dma_fault || `CORE.nx!==0)$fatal(1,"X bad index accepted");
   restart(0);
   // Sequence checking must not wait on the bank named by a malformed tag.
   // Expected bank0 is free; the bad tag incorrectly names occupied bank1.
   @(negedge clk);`CORE.x_valid=2'b10;
   drive(0,128,0);@(negedge clk);dma_x_valid=0;
   @(posedge clk);#1;
   if(!dma_fault || `CORE.nx!==0)$fatal(1,"occupied-bank bad X index did not fault");
   restart(0);
   drive(0,0,1);@(negedge clk);dma_x_valid=0;forbid_writes=1;
   @(posedge clk);#1;
   if(!dma_fault || `CORE.nx!==0 || dma_x_free!==2'b11)$fatal(1,"X overflow was not atomic");
   for(i=2;i<6;i=i+1)begin
     restart(0);drive(0,0,i);@(negedge clk);dma_x_valid=0;forbid_writes=1;
     @(posedge clk);#1;
     if(!dma_fault || `CORE.nx!==0 || dma_x_free!==2'b11)$fatal(1,"X positive overflow lane=%0d was not atomic",i-2);
   end
   restart(0);
   drive(0,0,0);forbid_writes=1;drive(0,2,0);
   @(negedge clk);dma_x_valid=0;
   @(posedge clk);#1;
   if(!dma_fault || `CORE.nx!==0)$fatal(1,"bad X sequence failed to discard pending commit");
   restart(0);drive(0,0,0);restart(1);
   restart(1);
   drive(0,0,0);@(negedge clk);dma_clear=1;dma_x_valid=0;forbid_writes=1;
   @(posedge clk);#1;
   if(`CORE.nx!==0 || dma_x_free!==2'b11)$fatal(1,"X pending survived clear");
   restart(0);
   @(negedge clk);dma_load_valid=1;dma_load_addr=20'h10000;
   @(posedge clk);#1;if(!dma_fault || `CORE.nx!==0)$fatal(1,"raw X accepted in delta mode");
   $display("X_BANK_PASS name=%0s tail=%0d values=%0d reads=%0d boundary_bubbles=%0d compute_overlap=1 overflow_lanes=4",test_name,TAIL_FIRST,scan_count,reads,full_bubbles);
   $finish;
 end
endmodule
