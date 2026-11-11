// Lossless formatter: independent assembly and a two-entry completed-group FIFO.
// Each queue entry owns its address. A stalled word and address remain stable.
module kwt_output_formatter #(parameter PACKED40=0) (
 input wire clk, rst_n, clear,
 input wire in_valid, output wire in_ready,
 input wire [39:0] in_data, input wire [14:0] in_index,
 output wire out_valid, input wire out_ready,
 output wire [31:0] out_data, output wire [15:0] out_index,
 output wire empty, output wire fault
);
 reg [119:0] partial;
 reg [1:0] gathered;
 reg [14:0] first_index;
 reg [159:0] payload [0:1];
 reg [15:0] address [0:1];
 reg head, tail;
 reg [1:0] count;
 reg [2:0] word_pos;
 reg fault_reg;
 localparam LAST_WORD = PACKED40 ? 4 : 1;
 wire enabled = rst_n && !clear && !fault_reg;
 wire retire = out_valid && out_ready && word_pos == LAST_WORD;
 wire space = count < 2 || retire;
 wire take = in_valid && in_ready;
 wire index_ok = !PACKED40 ||
                 (gathered == 0 ? in_index[1:0] == 0 :
                  {1'b0,in_index} == {1'b0,first_index}+gathered);
 wire publish = take && index_ok && (!PACKED40 || gathered == 3);
 assign in_ready = enabled && (PACKED40 && gathered != 3 || space);
 assign out_valid = enabled && count != 0;
 assign out_data = payload[head][word_pos*32 +: 32];
 assign out_index = address[head] + word_pos;
 assign empty = count == 0 && gathered == 0;
 assign fault = fault_reg;

 always @(posedge clk or negedge rst_n) begin
   if (!rst_n) begin
     partial<=0; gathered<=0; first_index<=0; head<=0; tail<=0;
     count<=0; word_pos<=0; fault_reg<=0;
     payload[0]<=0; payload[1]<=0; address[0]<=0; address[1]<=0;
   end else if (clear) begin
     partial<=0; gathered<=0; first_index<=0; head<=0; tail<=0;
     count<=0; word_pos<=0; fault_reg<=0;
     payload[0]<=0; payload[1]<=0; address[0]<=0; address[1]<=0;
   end else begin
     if (out_valid && out_ready) begin
       if (retire) begin head<=!head; word_pos<=0; end
       else word_pos<=word_pos+1'b1;
     end
     case ({publish,retire})
       2'b10: count<=count+1'b1;
       2'b01: count<=count-1'b1;
       default: begin end
     endcase
     if (take) begin
       if (!index_ok) fault_reg<=1;
       else if (!PACKED40) begin
         payload[tail]<={96'b0,{24{in_data[39]}},in_data};
         address[tail]<={in_index,1'b0};
         tail<=!tail;
       end else if (gathered==3) begin
         payload[tail]<={in_data,partial};
         address[tail]<=({3'b0,first_index[14:2]}<<2)+{3'b0,first_index[14:2]};
         tail<=!tail; gathered<=0;
       end else begin
         partial[gathered*40 +: 40]<=in_data;
         gathered<=gathered+1'b1;
         if (gathered==0) first_index<=in_index;
       end
     end
   end
 end
endmodule
