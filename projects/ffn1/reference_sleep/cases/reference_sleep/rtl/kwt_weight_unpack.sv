`timescale 1ns/1ps
// Exact, adjacent-column W16 reconstruction. Metadata contains eight 4-bit
// (signed-width - 1) descriptors per word, lowest column in the lowest nibble.
// Each quad carries K-even/K-odd from column c, then column c+1, LSB first.
// Quads have no padding; total payload remains two words per column width.
module kwt_weight_unpack #(parameter TAIL_FIRST=0) (
  input  wire        clk,
  input  wire        rst_n,
  input  wire        clear,
  input  wire        x_mode,
  input  wire        in_valid,
  output wire        in_ready,
  input  wire [31:0] in_word,
  output wire        out_valid,
  input  wire        out_ready,
  output wire [63:0] out_quad,
  output wire [67:0] out_residual,
  output wire [11:0] out_index,
  input  wire [3:0]  x_query_tile,
  output reg  [8:0]  x_query_words,
  output reg         metadata_valid,
  output reg  [13:0] expected_words,
  output reg         done,
  output reg         fault
);
  reg [31:0] metadata [0:31];
  reg [5:0] metadata_count;
  reg [13:0] input_count;
  reg [11:0] quad_index;
  reg mode_x;

  // The bus FIFO may fill while a reconstructed quad is stalled. Its validity
  // does not depend on the output consumer; the reservoir provides more slack.
  reg [31:0] input_fifo [0:1];
  reg fifo_wr, fifo_rd;
  reg [1:0] fifo_count;
  reg [95:0] reservoir;
  reg [6:0] bit_count;

  // q -> c=(q>>5)*2, k=(q&31)*2. One metadata word covers four
  // adjacent-column groups, and q[4:0] walks the 32 K pairs in a group.
  wire [3:0] even_code = metadata[quad_index[11:7]][quad_index[6:5]*8 +: 4];
  wire [3:0] odd_code = metadata[quad_index[11:7]][quad_index[6:5]*8+4 +: 4];
  wire [4:0] even_width = {1'b0, even_code} + 5'd1;
  wire [4:0] odd_width = {1'b0, odd_code} + 5'd1;
  wire [5:0] even_bits = {even_width, 1'b0};
  wire [6:0] w_quad_bits = {1'b0, even_width, 1'b0} + {1'b0, odd_width, 1'b0};
  wire [511:0] x_header;
  genvar h;
  generate for(h=0;h<16;h=h+1)begin:header_view
    assign x_header[h*32+:32]=metadata[h];
  end endgenerate
  wire [10:0] x_rest=quad_index[10:0]-11'd64;
  wire [10:0] x_tag=TAIL_FIRST ? (quad_index<64 ? 11'd1536+quad_index[10:0] :
                          {x_rest[10:7]^4'd1,x_rest[6:0]}) : quad_index[10:0];
  wire [6:0] x_row={x_tag[10:5],1'b0};
  wire [4:0] x_even_width=x_header[x_row*5+:5]+5'd1;
  wire [4:0] x_odd_width=x_row==98 ? 5'd0 : x_header[(x_row+1)*5+:5]+5'd1;
  wire [6:0] x_quad_bits={1'b0,x_even_width,1'b0}+{1'b0,x_odd_width,1'b0};
  wire [6:0] quad_bits=mode_x ? x_quad_bits : w_quad_bits;
  assign out_index = mode_x ? {1'b0,x_tag} : quad_index;
  assign out_valid = rst_n && !clear && metadata_valid && !done && !fault
                     && (bit_count >= quad_bits);
  wire output_take = out_valid && out_ready;

  function [15:0] extend_value;
    input [15:0] raw_value;
    input [4:0] width;
    reg [15:0] mask;
    begin
      mask = 16'hffff >> (5'd16 - width);
      extend_value = raw_value & mask;
      if (raw_value[width-1'b1])
        extend_value = extend_value | (16'hffff << width);
    end
  endfunction
  wire [95:0] even_k1 = reservoir >> even_width;
  wire [95:0] odd_k0 = reservoir >> even_bits;
  wire [95:0] odd_k1 = reservoir >> ({1'b0, even_bits} + {2'b0, odd_width});
  assign out_quad = {extend_value(odd_k1[15:0], odd_width),
                     extend_value(odd_k0[15:0], odd_width),
                     extend_value(even_k1[15:0], even_width),
                     extend_value(reservoir[15:0], even_width)};
  function [16:0] extend_residual;
    input [16:0] raw_value;
    input [4:0] width;
    reg [16:0] mask;
    begin
      mask=17'h1ffff>>(5'd17-width);
      extend_residual=raw_value&mask;
      if(raw_value[width-1'b1])extend_residual=extend_residual|(17'h1ffff<<width);
    end
  endfunction
  wire [95:0] x_even_k1=reservoir>>x_even_width;
  wire [95:0] x_odd_k0=reservoir>>{x_even_width,1'b0};
  wire [95:0] x_odd_k1=reservoir>>({1'b0,x_even_width,1'b0}+{2'b0,x_odd_width});
  assign out_residual={x_row==98 ? 17'd0 : extend_residual(x_odd_k1[16:0],x_odd_width),
                       x_row==98 ? 17'd0 : extend_residual(x_odd_k0[16:0],x_odd_width),
                       extend_residual(x_even_k1[16:0],x_even_width),
                       extend_residual(reservoir[16:0],x_even_width)};

  // At most seven descriptors finish in any 32-bit header word. Include the
  // preceding word for descriptors spanning a word boundary, and accumulate
  // only this bounded group, rather than a 99-row combinational adder chain.
  wire [63:0] x_header_fragment={in_word,metadata[(metadata_count-1'b1)&5'd15]};
  reg [8:0] x_header_words;
  reg x_header_bad;
  reg [4:0] x_code;
  integer xi,x_first,x_shift,x_end,query_row;
  always @* begin
    x_first=(metadata_count*32)/5;
    x_end=((metadata_count+1)*32)/5;
    x_shift=32-(metadata_count*32)%5;
    x_header_words=0;x_header_bad=0;x_code=0;
    for(xi=0;xi<7;xi=xi+1)begin
      if(x_first+xi<x_end && x_first+xi<99)begin
        x_code=5'(x_header_fragment>>(x_shift+xi*5));
        x_header_words=x_header_words+{3'd0,x_code,1'b0}+9'd2;
        if(x_code>16 || (((x_first+xi)%8)==0 && x_code==16))x_header_bad=1;
      end
    end
    if(metadata_count==15 && (in_word[31:16]!=16'h5844 || in_word[15]!=(TAIL_FIRST!=0)))x_header_bad=1;
  end
  integer qi;
  always @* begin
    x_query_words=0;query_row=0;
    for(qi=0;qi<8;qi=qi+1)begin
      query_row=x_query_tile*8+qi;
      if(query_row<99)x_query_words=x_query_words+{3'd0,x_header[query_row*5+:5],1'b0}+9'd2;
    end
  end

  assign in_ready = rst_n && !clear && !done && !fault
                    && (!metadata_valid ||
                        (input_count < expected_words && fifo_count < 2));
  wire input_take = in_valid && in_ready;
  wire fifo_push = input_take && metadata_valid;

  // Drain first, then append above the remaining low-order bits. An append
  // cannot change an offered quad, including when out_ready remains low.
  wire [6:0] remaining_bits = bit_count - (output_take ? quad_bits : 7'd0);
  wire [95:0] remaining_data = output_take ? reservoir >> quad_bits : reservoir;
  wire fifo_pop = metadata_valid && !done && !fault && fifo_count != 0
                  && remaining_bits <= 7'd64;
  wire [95:0] appended_word = {64'd0, input_fifo[fifo_rd]} << remaining_bits;

  function [8:0] metadata_payload_words;
    input [31:0] descriptors;
    integer nibble;
    reg [8:0] total;
    begin
      total = 0;
      for (nibble = 0; nibble < 8; nibble = nibble + 1)
        total = total + {4'd0, descriptors[nibble*4 +: 4], 1'b0} + 9'd2;
      metadata_payload_words = total;
    end
  endfunction

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      metadata_count <= 0;
      metadata_valid <= 0;
      expected_words <= 14'd32;
      input_count <= 0;
      quad_index <= 0;
      mode_x <= 0;
      fifo_wr <= 0;
      fifo_rd <= 0;
      fifo_count <= 0;
      reservoir <= 0;
      bit_count <= 0;
      done <= 0;
      fault <= 0;
    end else if (clear) begin
      metadata_count <= 0;
      metadata_valid <= 0;
      expected_words <= x_mode ? 14'd16 : 14'd32;
      input_count <= 0;
      quad_index <= 0;
      mode_x <= x_mode;
      fifo_wr <= 0;
      fifo_rd <= 0;
      fifo_count <= 0;
      reservoir <= 0;
      bit_count <= 0;
      done <= 0;
      fault <= 0;
    end else begin
      if (input_take) begin
        input_count <= input_count + 1'b1;
        if (!metadata_valid) begin
          metadata[metadata_count[4:0]] <= in_word;
          expected_words <= expected_words + {5'd0, mode_x ? x_header_words : metadata_payload_words(in_word)};
          metadata_count <= metadata_count + 1'b1;
          if(mode_x && x_header_bad)fault<=1;
          else if(metadata_count==(mode_x ? 15 : 31))metadata_valid<=1;
        end
      end
      if (fifo_push) begin
        input_fifo[fifo_wr] <= in_word;
        fifo_wr <= ~fifo_wr;
      end
      if (fifo_pop) fifo_rd <= ~fifo_rd;
      case ({fifo_push, fifo_pop})
        2'b10: fifo_count <= fifo_count + 1'b1;
        2'b01: fifo_count <= fifo_count - 1'b1;
        default: ;
      endcase
      if (output_take || fifo_pop) begin
        reservoir <= remaining_data | (fifo_pop ? appended_word : 96'd0);
        bit_count <= remaining_bits + (fifo_pop ? 7'd32 : 7'd0);
      end
      if (output_take) begin
        if (quad_index == (mode_x ? 12'd1599 : 12'd4095)) begin
          done <= 1;
          if (input_count != expected_words || remaining_bits != 0 || fifo_count != 0)
            fault <= 1;
        end else quad_index <= quad_index + 1'b1;
      end
      if (fifo_count > 2 || bit_count > 96) fault <= 1;
    end
  end
endmodule
