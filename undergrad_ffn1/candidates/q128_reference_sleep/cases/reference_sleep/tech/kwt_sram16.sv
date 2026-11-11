// Backend-only replacement for rtl/kwt_sram16.sv. Never compile both files.
// Native synchronous single-port RAMSP macros; one read OR write per cycle.
// No reset, extra read register, or changes to read latency.
// Shared SRAM/TCM retain their clock by default; only local tile SRAM opts in.
`include "sram_config.vh"
module kwt_sram16 #(parameter AW=12,GATE_CLK=0)(
    input wire clk,cs,we,
    input wire [AW-1:0] addr,
    input wire [15:0] din,
    output wire [15:0] dout
);
    wire macro_clk;
    generate if(GATE_CLK) begin:gated_clock
        kwt_sram_clock_gate clock_gate(.clk(clk),.enable(cs),.gated_clk(macro_clk));
    end else begin:ungated_clock
        assign macro_clk=clk;
    end endgenerate
    wire cen=~cs;
    wire gwen=~we;
    generate
        if(AW==7) begin: native128
            RAMSP128X16 u_macro(
                .Q(dout),.CLK(macro_clk),.CEN(cen),.WEN(16'b0),.A(addr),.D(din),
                .EMA(`KWT_SRAM_EMA),.EMAW(`KWT_SRAM_EMAW),
                .GWEN(gwen),.RET1N(1'b1));
        end else if(AW==10) begin: native1024
            RAMSP1024X16 u_macro(
                .Q(dout),.CLK(macro_clk),.CEN(cen),.WEN(16'b0),.A(addr),.D(din),
                .EMA(`KWT_SRAM_EMA),.EMAW(`KWT_SRAM_EMAW),
                .GWEN(gwen),.RET1N(1'b1));
        end else if(AW==12) begin: native4096
            RAMSP4096X16 u_macro(
                .Q(dout),.CLK(macro_clk),.CEN(cen),.WEN(16'b0),.A(addr),.D(din),
                .EMA(`KWT_SRAM_EMA),.EMAW(`KWT_SRAM_EMAW),
                .GWEN(gwen),.RET1N(1'b1));
        end else begin: unsupported
            KWT_UNSUPPORTED_SRAM_ADDRESS_WIDTH invalid_configuration();
        end
    endgenerate
endmodule
