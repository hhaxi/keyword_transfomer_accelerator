// Structural-check leaves only. DC links real .db cells instead.
(* blackbox *) module RAMSP128X16(output [15:0] Q,input CLK,CEN,input [15:0] WEN,
    input [6:0] A,input [15:0] D,input [2:0] EMA,input [1:0] EMAW,input GWEN,RET1N);
endmodule
(* blackbox *) module RAMSP1024X16(output [15:0] Q,input CLK,CEN,input [15:0] WEN,
    input [9:0] A,input [15:0] D,input [2:0] EMA,input [1:0] EMAW,input GWEN,RET1N);
endmodule
(* blackbox *) module RAMSP4096X16(output [15:0] Q,input CLK,CEN,input [15:0] WEN,
    input [11:0] A,input [15:0] D,input [2:0] EMA,input [1:0] EMAW,input GWEN,RET1N);
endmodule
