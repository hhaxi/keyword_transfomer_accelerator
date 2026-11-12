`timescale 1ns/1ps
module memory_case #(parameter AW=7)(output reg done=0);
 reg clk=0;always #5 clk=~clk;
 reg cs=0,we=0;reg [AW-1:0] addr=0;reg [15:0] din=0;
 wire [15:0] q;reg [15:0] expected[0:(1<<AW)-1];reg [15:0] prev;
 kwt_sram16 #(.AW(AW)) dut(clk,cs,we,addr,din,q);
 initial begin
  for(integer i=0;i<(1<<AW);i=i+1) begin
   @(negedge clk);cs=1;we=1;addr=i;din=(i*17)^16'hb53a;expected[i]=din;
  end
  for(integer i=0;i<(1<<AW);i=i+1) begin
   @(negedge clk);we=0;addr=i;@(posedge clk);#1;
   if(q!==expected[i]) $fatal(1,"SRAM mismatch AW=%0d addr=%0d",AW,i);
   prev=q;@(negedge clk);cs=0;@(posedge clk);#1;
   if(q!==prev) $fatal(1,"SRAM output changed with CS low");
   @(negedge clk);cs=1;
  end
  done=1;
 end
endmodule
module tb_memories;
 wire [6:0] done;
 memory_case #(6) a(done[0]);memory_case #(7) b(done[1]);memory_case #(8) c(done[2]);
 memory_case #(9) d(done[3]);memory_case #(10) e(done[4]);memory_case #(11) f(done[5]);memory_case #(12) g(done[6]);
 initial begin wait(&done);$display("ASIC_MEMORY_PASS all logical widths 6..12");$finish;end
 initial begin #300000;$fatal(1,"memory test timeout");end
endmodule
