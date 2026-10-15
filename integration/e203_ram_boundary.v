// Synthesis-only boundary matching the upstream sirv_gnrl_ram interface.
// Upstream functional model is used for simulation; official SRAM mapping is pending.
(* blackbox *) module sirv_gnrl_ram #(
    parameter DP=32,DW=32,FORCE_X2ZERO=1,MW=4,AW=15
)(
    input sd,ds,ls,rst_n,clk,cs,we,
    input [AW-1:0] addr,input [DW-1:0] din,input [MW-1:0] wem,
    output [DW-1:0] dout
);
endmodule
