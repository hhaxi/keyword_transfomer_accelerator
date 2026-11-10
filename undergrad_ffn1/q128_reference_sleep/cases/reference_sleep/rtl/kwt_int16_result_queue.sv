// Hold one tile. The last pair and the next tile can transfer together.
module kwt_int16_result_queue #(
    parameter ROWS = 4,
    parameter COLS = 16
) (
    input wire clk, rst_n, clear,
    input wire in_valid, output wire in_ready,
    input wire [ROWS*COLS*40-1:0] in_values,
    input wire [6:0] in_row, input wire [7:0] in_col,
    input wire [$clog2(ROWS):0] in_rows,
    output wire out_valid, input wire out_ready,
    output wire [31:0] out_word, output wire [14:0] out_index
);
    localparam ROW_BITS = $clog2(ROWS);
    localparam PAIR_COL_BITS = $clog2(COLS/2);
    localparam PAIR_BITS = ROW_BITS + PAIR_COL_BITS;
    reg full;
    reg [6:0] row_base;
    reg [6:0] column_pair_base;
    reg [ROW_BITS-1:0] last_row;
    reg [PAIR_BITS-1:0] pair_index;
    reg [79:0] pairs [0:ROWS*COLS/2-1];
    wire [79:0] pair_values = pairs[pair_index];
    wire [ROW_BITS-1:0] row_offset = pair_index[PAIR_BITS-1:PAIR_COL_BITS];
    wire [PAIR_COL_BITS-1:0] column_offset = pair_index[PAIR_COL_BITS-1:0];
    wire take = out_valid && out_ready;
    wire last_pair = (row_offset == last_row) && (&column_offset);
    wire release_group = take && last_pair;
    wire publish = in_valid && in_ready;

    assign out_valid = rst_n && !clear && full;
    assign in_ready = rst_n && !clear && (!full || release_group);
    wire [6:0] row = row_base + 7'(row_offset);
    wire [6:0] column_pair = column_pair_base + 7'(column_offset);
    assign out_index = {1'b0, row, column_pair};

    function automatic [15:0] quantize(input signed [39:0] value);
        reg signed [25:0] rounded;
        begin
            // Arithmetic floor, with a nonnegative remainder. At a tie keep
            // the even integer. The extra bit prevents rounding overflow.
            rounded = $signed({value[39], value[39:15]});
            if (value[14:0] > 15'd16384 ||
                (value[14:0] == 15'd16384 && rounded[0]))
                rounded = rounded + 26'sd1;
            if (rounded > 26'sd32767)
                quantize = 16'h7fff;
            else if (rounded < -26'sd32768)
                quantize = 16'h8000;
            else
                quantize = rounded[15:0];
        end
    endfunction

    assign out_word = {quantize(pair_values[79:40]), quantize(pair_values[39:0])};
    genvar j;
    generate for (j=0; j<ROWS*COLS/2; j=j+1) begin : pair_storage
        always @(posedge clk)
            if (publish) pairs[j] <= in_values[j*80+:80];
    end endgenerate

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            full <= 0;
            row_base <= 0;
            column_pair_base <= 0;
            last_row <= 0;
            pair_index <= 0;
        end else if (clear) begin
            full <= 0;
            pair_index <= 0;
        end else if (publish) begin
            full <= 1;
            row_base <= in_row;
            column_pair_base <= in_col[7:1];
            last_row <= ROW_BITS'(in_rows - 1'b1);
            pair_index <= 0;
        end else if (take) begin
            if (last_pair) full <= 0;
            else pair_index <= pair_index + 1'b1;
        end
    end
endmodule
