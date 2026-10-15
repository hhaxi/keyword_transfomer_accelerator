`timescale 1ns/1ps
module tb_mac_probe;
  reg clk = 0;
  reg rst_n = 0;
  reg en = 0;
  reg signed [15:0] a = 0, b = 0;
  wire signed [39:0] sum;
  reg signed [39:0] expected = 0;
  integer i;
  mac_probe dut(clk, rst_n, en, a, b, sum);
  always #5 clk = ~clk;
  initial begin
    $dumpfile("mac_probe.vcd");
    $dumpvars(0, tb_mac_probe);
    repeat (2) @(negedge clk);
    if (sum !== 0) $fatal(1, "Reset failed");
    rst_n = 1;
    for (i = 0; i < 64; i = i + 1) begin
      a = i - 32; b = 17 - i; en = 1;
      expected = expected + (i - 32) * (17 - i);
      @(negedge clk);
    end
    en = 0;
    if (sum !== expected) $fatal(1, "MAC mismatch: %d != %d", sum, expected);
    repeat (3) @(negedge clk);
    if (sum !== expected) $fatal(1, "Enable hold failed");
    rst_n = 0;
    @(negedge clk);
    if (sum !== 0) $fatal(1, "Second reset failed");
    $display("RTL_ENVIRONMENT_PASS sum=%0d", expected);
    $finish;
  end
endmodule
