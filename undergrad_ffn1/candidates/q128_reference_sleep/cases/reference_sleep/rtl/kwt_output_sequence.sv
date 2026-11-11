// Fixed q64 schedule: 4 rows x 8 columns, then the next 8-column group.
// The final tile contains rows 96..98 only. Advance ONLY on accepted values.
module kwt_output_sequence(
 input wire clk,rst_n,clear,advance,
 output wire [14:0] index,
 output wire [4:0] lane,
 output wire last_lane
);
 reg [6:0] row_base;
 reg [4:0] column_group,lane_reg;
 wire [6:0] result_row=row_base+{5'b0,lane_reg[4:3]};
 assign index={result_row,column_group,lane_reg[2:0]};
 assign lane=lane_reg;
 assign last_lane=(row_base==96) ? lane_reg==23 : lane_reg==31;
 always @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin row_base<=0;column_group<=0;lane_reg<=0;end
   else if(clear) begin row_base<=0;column_group<=0;lane_reg<=0;end
   else if(advance) begin
     if(last_lane) begin
       lane_reg<=0;
       column_group<=column_group+1'b1;
       if(column_group==31) row_base<=row_base+7'd4;
     end else lane_reg<=lane_reg+1'b1;
   end
 end
endmodule
