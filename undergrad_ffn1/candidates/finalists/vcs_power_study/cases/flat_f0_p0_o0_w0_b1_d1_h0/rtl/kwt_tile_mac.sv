module kwt_tile_mac #(parameter KPAR=2, PRODUCT_PIPE=0)(
 input wire clk,rst_n,clear,valid,first,
 input wire signed [15:0] x0,w0,x1,w1,input wire signed [31:0] bias,
 output reg signed [39:0] acc);
 wire signed [31:0] p0=x0*w0;
 wire signed [39:0] sum;
 generate if(KPAR==2)begin:g_two
 wire signed [31:0] p1=x1*w1;
 assign sum={{8{p0[31]}},p0}+{{8{p1[31]}},p1};
 end else begin:g_one
 assign sum={{8{p0[31]}},p0};end endgenerate
 generate if(PRODUCT_PIPE)begin:g_pipe
 reg v,f;reg signed [39:0] product;reg signed [31:0] seed;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin v<=0;f<=0;product<=0;seed<=0;acc<=0;end
 else if(clear)begin v<=0;acc<=0;end
 else begin v<=valid;if(valid)begin product<=sum;f<=first;seed<=bias;end
 if(v)acc<=(f ? {{8{seed[31]}},seed} : acc)+product;end end
 end else begin:g_direct
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)acc<=0;else if(clear)acc<=0;
 else if(valid)acc<=(first ? {{8{bias[31]}},bias} : acc)+sum;end
 end endgenerate
endmodule
