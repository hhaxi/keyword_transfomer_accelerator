`timescale 1ns/1ps
module tb_clock_gate;
 reg clk=0;always #5 clk=~clk;
 reg en=0,test_en=0;
 wire gclk;
 kwt_clock_gate dut(.*);
 integer root_edges=0,gate_edges=0,expected_edges=0,enabled_cycles=0,disabled_cycles=0;
 integer i;reg allowed;
 time root_rise=0,gate_rise=0;
 bit ever_opened=0;
 reg [31:0] rng=32'hf173cc20;
 always @(posedge clk)begin
   root_rise=$time;root_edges++;
   allowed=en|test_en;
   if(allowed)begin expected_edges++;enabled_cycles++;end
   else disabled_cycles++;
   #0.001;
   if(gclk!==allowed || gate_edges!=expected_edges)$fatal(1,"Gate missing/extra edge");
 end
 always @(posedge gclk)begin
   if(clk!==1'b1 || $time!=root_rise)$fatal(1,"Glitch: rising edge outside root rise");
   gate_edges++;gate_rise=$time;ever_opened=1;
 end
 always @(negedge gclk)if(ever_opened)begin
   if(clk!==1'b0 || $time-gate_rise!=5)$fatal(1,"Truncated gated high pulse");
 end
 initial begin
   repeat(4)@(negedge clk);
   for(i=0;i<500;i++)begin
     @(negedge clk);#1;
     rng=rng*1664525+1013904223;en=rng[4];test_en=(rng[7:5]==0);
     // High-phase toggles must never create, truncate or duplicate a clock edge.
     @(posedge clk);#1;en=~en;test_en=~test_en;
     #1;en=~en;test_en=~test_en;
   end
   @(negedge clk);#1;en=0;test_en=1;
   repeat(4)@(negedge clk);
   #1;test_en=0;repeat(4)@(negedge clk);
   if(enabled_cycles<100 || disabled_cycles<100)$fatal(1,"Insufficient gate coverage");
   $display("CLOCK_GATE_PASS root=%0d passed=%0d disabled=%0d",root_edges,gate_edges,disabled_cycles);
   $finish;
 end
 initial begin #100000;$fatal(1,"Clock-gate timeout");end
endmodule
