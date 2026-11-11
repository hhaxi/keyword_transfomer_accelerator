// Signed 16 x 16 products, exact signed 40-bit accumulation, no rounding.
module kwt_mac40(
    input wire clk, rst_n, init, enable,
    input wire signed [15:0] x, w,
    input wire signed [31:0] bias,
    output reg signed [39:0] acc
);
    wire signed [31:0] product = x * w;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) acc <= 40'sd0;
        else if (init) acc <= {{8{bias[31]}}, bias};
        else if (enable) acc <= acc + {{8{product[31]}}, product};
endmodule
