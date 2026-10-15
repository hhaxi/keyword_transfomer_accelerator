`timescale 1ns/1ps
`include "math_size.vh"
module tb_encoder_math;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,clear=0,div_start=0,sqrt_start=0;
    reg [63:0] numerator=0,value=0;reg [31:0] denominator=1;reg [32:0] delta=0;
    wire db,dd,sb,sd;wire [63:0] quotient;wire [31:0] root,result;
    reg [159:0] dv[0:`DIV_CASES-1];reg [95:0] sq[0:`SQ_CASES-1],ex[0:`EXP_CASES-1];
    integer i;
    kwt_udiv64 divide(clk,rst_n,clear,div_start,numerator,denominator,db,dd,quotient);
    kwt_isqrt64 sqrt_(clk,rst_n,clear,sqrt_start,value,sb,sd,root);
    kwt_exp_negative exp_(delta,result);
    initial begin
        $readmemh("output/encoder-math/divide.hex",dv);$readmemh("output/encoder-math/sqrt.hex",sq);$readmemh("output/encoder-math/exp.hex",ex);
        repeat(3) @(negedge clk);rst_n=1;
        for(i=0;i<`DIV_CASES;i++) begin
            @(negedge clk);numerator=dv[i][159:96];denominator=dv[i][95:64];div_start=1;
            @(negedge clk);div_start=0;
            while(!dd) @(negedge clk);
            if(quotient!==dv[i][63:0] || db) $fatal(1,"Divide mismatch %0d",i);
        end
        for(i=0;i<`SQ_CASES;i++) begin
            @(negedge clk);value=sq[i][95:32];sqrt_start=1;
            @(negedge clk);sqrt_start=0;
            while(!sd) @(negedge clk);
            if(root!==sq[i][31:0] || sb) $fatal(1,"Sqrt mismatch %0d",i);
        end
        for(i=0;i<`EXP_CASES;i++) begin
            delta=ex[i][64:32];#1;
            if(result!==ex[i][31:0]) $fatal(1,"Exp mismatch %0d",i);
        end
        @(negedge clk);div_start=1;sqrt_start=1;
        @(negedge clk);div_start=0;sqrt_start=0;
        repeat(7) @(negedge clk);clear=1;
        @(negedge clk);clear=0;
        repeat(70) begin @(negedge clk);if(db || sb || dd || sd) $fatal(1,"Canceled operation reappeared");end
        $display("ENC_MATH_PASS divide=%0d sqrt=%0d exp=%0d clear",`DIV_CASES,`SQ_CASES,`EXP_CASES);$finish;
    end
endmodule
