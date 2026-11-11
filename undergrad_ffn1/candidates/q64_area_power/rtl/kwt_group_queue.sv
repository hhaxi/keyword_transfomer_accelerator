// Constant-lane group writes avoid the generic FIFO's multiwrite barrel mux.
// DEPTH=1 reuses the current bank on its last accepted result, with no bubble.
module kwt_group_queue #(parameter DEPTH=2)(
 input wire clk,rst_n,clear,
 input wire in_valid,output wire in_ready,
 input wire [1279:0] in_values,
 output wire out_valid,input wire out_ready,
 output wire [39:0] out_value,output wire [14:0] out_index
);
 generate if(DEPTH!=1 && DEPTH!=2)begin:bad_depth
   KWT_UNSUPPORTED_GROUP_DEPTH invalid_configuration();
 end endgenerate
 reg read_bank,write_bank;
 reg [1:0] groups;
 wire [4:0] lane;
 wire last_lane;
 wire take=out_valid && out_ready;
 wire release_group=take && last_lane;
 wire publish=in_valid && in_ready;
 assign out_valid=rst_n && !clear && groups!=0;
 assign in_ready=rst_n && !clear && (groups<DEPTH || release_group);
 kwt_output_sequence sequence_gen(.clk(clk),.rst_n(rst_n),.clear(clear),
   .advance(take),.index(out_index),.lane(lane),.last_lane(last_lane));
 wire [39:0] bank_output[0:DEPTH-1];
 genvar b,j;
 generate for(b=0;b<DEPTH;b=b+1)begin:banks
   reg [39:0] values[0:31];
   for(j=0;j<32;j=j+1)begin:lanes
     // Data need not reset: groups is cleared before any read is valid.
     always @(posedge clk)
       if(publish && write_bank==b) values[j]<=in_values[j*40+:40];
   end
   assign bank_output[b]=values[lane];
 end
 if(DEPTH==1)begin:one
   assign out_value=bank_output[0];
 end else begin:two
   assign out_value=read_bank ? bank_output[1] : bank_output[0];
 end endgenerate
 always @(posedge clk or negedge rst_n)begin
   if(!rst_n)begin read_bank<=0;write_bank<=0;groups<=0;end
   else if(clear)begin read_bank<=0;write_bank<=0;groups<=0;end
   else begin
     case({publish,release_group})
       2'b10:groups<=groups+1'b1;
       2'b01:groups<=groups-1'b1;
       default:begin end
     endcase
     if(publish)write_bank<=(DEPTH==2) ? !write_bank : 1'b0;
     if(release_group)read_bank<=(DEPTH==2) ? !read_bank : 1'b0;
   end
 end
endmodule
