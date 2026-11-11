module kwt_output_formatter #(parameter PACKED40=0) (
 input wire clk, rst_n, clear,
 input wire in_valid, output wire in_ready,
 input wire [39:0] in_data, input wire [14:0] in_index,
 output wire out_valid, input wire out_ready,
 output wire [31:0] out_data, output wire [15:0] out_index,
 output wire empty, output wire fault
);
 // One complete output group plus partial-group assembly. The final word may
 // drain on the same edge as the first value of the next group is accepted.
 reg [159:0] payload;
 reg [2:0] words_left;
 reg [1:0] gathered;
 reg [14:0] first_index;
 reg [15:0] word_index;
 reg fault_reg;
 wire final_drain = (words_left == 1) && out_ready;
 assign in_ready = rst_n && !clear && !fault_reg &&
                   ((words_left == 0) || final_drain);
 assign out_valid = rst_n && !clear && (words_left != 0);
 assign out_data = payload[31:0];
 assign out_index = word_index;
 assign empty = (words_left == 0) && (gathered == 0);
 assign fault = fault_reg;

 always @(posedge clk or negedge rst_n) begin
   if (!rst_n) begin
     payload <= 0;
     words_left <= 0;
     gathered <= 0;
     first_index <= 0;
     word_index <= 0;
     fault_reg <= 0;
   end else if (clear) begin
     payload <= 0;
     words_left <= 0;
     gathered <= 0;
     first_index <= 0;
     word_index <= 0;
     fault_reg <= 0;
   end else begin
     if (out_valid && out_ready) begin
       payload <= payload >> 32;
       words_left <= words_left - 1'b1;
       word_index <= word_index + 1'b1;
     end
     if (in_valid && in_ready) begin
       if (!PACKED40) begin
         payload <= {96'b0, {24{in_data[39]}}, in_data};
         words_left <= 2;
         word_index <= {in_index,1'b0};
       end else if (gathered == 0) begin
         if (in_index[1:0] != 0) begin
           fault_reg <= 1;
         end else begin
           // Whole assignment overrides any simultaneous final-word shift.
           payload <= {120'b0,in_data};
           first_index <= in_index;
           gathered <= 1;
         end
       end else if ({1'b0,in_index} != ({1'b0,first_index}+gathered)) begin
         fault_reg <= 1;
       end else begin
         payload[gathered*40 +: 40] <= in_data;
         if (gathered == 3) begin
           gathered <= 0;
           words_left <= 5;
           // Explicit 16-bit expression prevents truncation at maximum index.
           word_index <= ({3'b0,first_index[14:2]} << 2) +
                          {3'b0,first_index[14:2]};
         end else gathered <= gathered + 1'b1;
       end
     end
   end
 end
endmodule
