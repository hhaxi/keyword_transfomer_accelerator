`timescale 1ns/1ps
module RAMSP128X16(output reg [15:0] Q,input wire CLK,CEN,GWEN,
 input wire [15:0] WEN,D,input wire [6:0] A,input wire [2:0] EMA,input wire [1:0] EMAW,input wire RET1N);
 reg [15:0] mem[0:127];
 always @(posedge CLK) if(!CEN) begin
  if(!GWEN) begin
   for(integer i=0;i<16;i=i+1) if(!WEN[i]) mem[A][i]<=D[i];
  end
  else Q<=mem[A];
 end
endmodule
module RAMSP1024X16(output reg [15:0] Q,input wire CLK,CEN,GWEN,
 input wire [15:0] WEN,D,input wire [9:0] A,input wire [2:0] EMA,input wire [1:0] EMAW,input wire RET1N);
 reg [15:0] mem[0:1023];
 always @(posedge CLK) if(!CEN) begin
  if(!GWEN) begin
   for(integer i=0;i<16;i=i+1) if(!WEN[i]) mem[A][i]<=D[i];
  end
  else Q<=mem[A];
 end
endmodule
module RAMSP4096X16(output reg [15:0] Q,input wire CLK,CEN,GWEN,
 input wire [15:0] WEN,D,input wire [11:0] A,input wire [2:0] EMA,input wire [1:0] EMAW,input wire RET1N);
 reg [15:0] mem[0:4095];
 always @(posedge CLK) if(!CEN) begin
  if(!GWEN) begin
   for(integer i=0;i<16;i=i+1) if(!WEN[i]) mem[A][i]<=D[i];
  end
  else Q<=mem[A];
 end
endmodule
