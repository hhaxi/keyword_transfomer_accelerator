// Exact for bias + 64 signed INT16 products: magnitude < 2^37.
// Keep the public INT40 result; no rounding, truncation of values or saturation.
module kwt_tile_mac #(parameter KPAR=2, PRODUCT_PIPE=0)(
 input wire clk,rst_n,clear,valid,first,
 input wire signed [15:0] x0,w0,x1,w1,input wire signed [31:0] bias,
 output wire signed [39:0] acc
);
 generate if(KPAR!=2 || PRODUCT_PIPE!=0)begin:unsupported
   KWT_NARROW_REQUIRES_Q64_DIRECT invalid_configuration();
 end endgenerate
 wire signed [31:0] p0=x0*w0,p1=x1*w1;
 wire signed [32:0] pair_sum={p0[31],p0}+{p1[31],p1};
 wire signed [37:0] sum_extended={{5{pair_sum[32]}},pair_sum};
 wire signed [37:0] bias_extended={{6{bias[31]}},bias};
 reg signed [37:0] accumulator;
 assign acc={{2{accumulator[37]}},accumulator};
 always @(posedge clk or negedge rst_n)begin
   if(!rst_n)accumulator<=0;
   else if(clear)accumulator<=0;
   else if(valid)accumulator<=(first ? bias_extended : accumulator)+sum_extended;
 end
endmodule
