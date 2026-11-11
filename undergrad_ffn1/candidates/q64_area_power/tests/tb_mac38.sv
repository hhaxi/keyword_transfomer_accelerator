`timescale 1ns/1ps
module tb_mac38;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,clear=0,valid=0,first=0;
 reg signed [15:0] x0=0,w0=0,x1=0,w1=0;
 reg signed [31:0] bias=0;
 wire signed [39:0] acc;
 kwt_tile_mac dut(.*);
 reg signed [63:0] expected=0,product0,product1;
 reg [31:0] random_state=32'h1234abce;
 integer g,k,checked=0;
 function automatic [31:0] rand_next(input [31:0] x);rand_next=x*1664525+1013904223;endfunction
 task automatic step;
   @(posedge clk);
   if(!rst_n || clear)expected=0;
   else if(valid)begin
     product0=x0;product0=product0*w0;
     product1=x1;product1=product1*w1;
     if(first)expected=bias;
     expected=expected+product0+product1;
   end
   #1;
   if($signed(acc)!==expected) $fatal(1,"MAC mismatch group=%0d k=%0d got=%0d expected=%0d",g,k,$signed(acc),expected);
   checked++;
 endtask
 initial begin
   step();@(negedge clk);rst_n=1;
   for(g=0;g<1000;g++) begin
     for(k=0;k<32;k++)begin
       @(negedge clk);
       random_state=rand_next(random_state);x0=random_state[15:0];
       random_state=rand_next(random_state);w0=random_state[15:0];
       random_state=rand_next(random_state);x1=random_state[15:0];
       random_state=rand_next(random_state);w1=random_state[15:0];
       random_state=rand_next(random_state);bias=random_state;
       if(g==0)begin x0=-32768;w0=-32768;x1=-32768;w1=-32768;bias=32'h7fffffff;end
       if(g==1)begin x0=-32768;w0=32767;x1=-32768;w1=32767;bias=32'h80000000;end
       if(g==2)begin x0=-32768;w0=-32768;x1=-32768;w1=32767;bias=32'h80000000;end
       valid=1;first=k==0;clear=0;step();
       // Invalid cycles still toggle the input pins; accumulation must hold.
       if(g>3 && random_state[2:0]<3)begin
         @(negedge clk);valid=0;first=1;x0=~x0;w1=~w1;bias=~bias;step();
       end
     end
     // Every group's first product follows the previous group without clear.
     if(g%7==6)begin @(negedge clk);clear=1;valid=1;step();end
   end
   @(negedge clk);clear=0;valid=1;first=1;bias=17;x0=3;w0=-5;x1=7;w1=2;step();
   @(negedge clk);rst_n=0;step();
   $display("MAC38_PASS groups=1000 pairs=32000 checked=%0d",checked);$finish;
 end
endmodule
