`timescale 1ns/1ps
module tb_mac;
    reg clk=0; always #3.333 clk=~clk;
    reg rst_n=0,init=0,enable=0;
    reg signed [15:0] x=0,w=0;
    reg signed [31:0] bias=0;
    wire signed [39:0] acc;
    reg signed [63:0] expected;
    integer t,k; reg [31:0] rng=32'h12345678;
    kwt_mac40 dut(.*);
    function [31:0] next_rng(input [31:0] r);
        reg [31:0] q; begin q=r^(r<<13); q=q^(q>>17); next_rng=q^(q<<5); end
    endfunction
    initial begin
        if($test$plusargs("vcd")) begin $dumpfile("output/mac.vcd");$dumpvars(0,tb_mac);end
        repeat(3) @(negedge clk); rst_n=1;
        for(t=0;t<100;t=t+1) begin
            @(negedge clk); init=1; enable=0;
            bias=(t==0)?32'h80000000:(t==1)?32'h7fffffff:$signed(rng);
            expected={{32{bias[31]}},bias};
            @(negedge clk); init=0;
            if(acc!==expected[39:0]) $fatal(1,"bias mismatch");
            for(k=0;k<64;k=k+1) begin
                rng=next_rng(rng); x=(t<2)?-16'sd32768:$signed(rng[15:0]);
                rng=next_rng(rng); w=(t<2)?-16'sd32768:$signed(rng[15:0]);
                enable=1; expected=expected+64'($signed(x)*$signed(w));
                @(negedge clk);
                if(acc!==expected[39:0]) $fatal(1,"MAC mismatch t=%0d k=%0d",t,k);
                enable=0; @(negedge clk);
                if(acc!==expected[39:0]) $fatal(1,"enable hold mismatch");
            end
        end
        init=1;bias=32'sd17;@(negedge clk);init=0;enable=1;x=-32768;w=32767;
        repeat(5) @(negedge clk);
        rst_n=0; @(negedge clk);
        if(acc!==0) $fatal(1,"reset mismatch");
        $display("MAC_PASS 100 dot products, extremes, signed random, stalls, reset"); $finish;
    end
endmodule
