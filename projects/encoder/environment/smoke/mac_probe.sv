// Environment probe only; this is not the competition accelerator.
module mac_probe(input wire clk, input wire rst_n, input wire en,
                 input wire signed [15:0] a, b,
                 output reg signed [39:0] sum);
  wire signed [31:0] product = a * b;
  always @(posedge clk) begin
    if (!rst_n) sum <= 0;
    else if (en) sum <= sum + {{8{product[31]}}, product};
  end
endmodule
