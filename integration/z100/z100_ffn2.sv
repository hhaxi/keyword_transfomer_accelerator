// Tiled GELU and second linear layer for the Z100 FFN1 stream.
module z100_ffn2 #(parameter OVERLAP=0) (
    input wire clk, rst_n, clear,
    input wire weight_write,
    input wire [12:0] weight_index,
    input wire [31:0] weight_data,
    input wire bias_write,
    input wire [5:0] bias_index,
    input wire [31:0] bias_data,
    input wire [4:0] gelu_input_shift, gelu_output_shift,
    input wire input_valid,
    output wire input_ready,
    input wire signed [39:0] input_data,
    output wire output_valid,
    input wire output_ready,
    output wire [63:0] output_data
);
    localparam FILL = 3'd0, PRIME = 3'd1, MAC = 3'd2,
               LAST = 3'd3, MERGE = 3'd4, SEND = 3'd5, COMPLETE = 3'd6;
    reg [2:0] state;
    reg [6:0] rows_seen;
    reg [7:0] fill_feature;
    reg [2:0] fill_row, compute_row, tile_last_row, group_index, output_lane;
    reg [6:0] k_pair;
    reg final_tile;
    reg [39:0] sums [0:7];
    wire [15:0] activation [0:1];
    wire signed [15:0] gelu;
    wire gelu_saturated;
    wire fill = input_ready && input_valid;
    wire operands_read = state == PRIME || state == MAC;
    wire mac_enable = state == MAC || state == LAST;
    wire [9:0] activation_address = fill ?
        {fill_row, fill_feature[7:1]} : {compute_row, k_pair};

    reg fill_page,compute_page;
    reg [1:0] tile_full;
    wire tile_end=fill && fill_feature==255 && (fill_row==7 || rows_seen==98);
    wire tile_consumed=state==SEND && output_ready && output_lane==7 &&
                       group_index==7 && compute_row==tile_last_row;
    assign input_ready = OVERLAP ? !tile_full[fill_page] && rows_seen<99 : state == FILL;
    assign output_valid = state == SEND;
    assign output_data = {{24{sums[output_lane][39]}}, sums[output_lane]};

    kwt_gelu gelu_unit(.value(input_data), .input_shift(gelu_input_shift),
        .output_shift(gelu_output_shift), .result(gelu), .saturated(gelu_saturated));

    genvar lane, parity;
    generate
        for (parity = 0; parity < 2; parity = parity + 1) begin: activation_banks
            wire store = fill && fill_feature[0] == (parity == 1);
            if(OVERLAP) begin: ping_pong
                wire [15:0] page_q[0:1];
                assign activation[parity]=page_q[compute_page];
                for(genvar page=0;page<2;page=page+1) begin: pages
                    wire writing=store && fill_page==page;
                    kwt_sram16 #(.AW(10)) memory(.clk(clk),
                        .cs(writing || (operands_read && compute_page==page)),.we(writing),
                        .addr(writing ? {fill_row,fill_feature[7:1]} : {compute_row,k_pair}),
                        .din(gelu),.dout(page_q[page]));
                end
            end else begin: single_page
                kwt_sram16 #(.AW(10)) memory(.clk(clk), .cs(store || operands_read),
                    .we(store), .addr(activation_address), .din(gelu), .dout(activation[parity]));
            end
        end
        for (lane = 0; lane < 8; lane = lane + 1) begin: columns
            reg [31:0] biases [0:7];
            wire signed [39:0] accumulators [0:1];
            wire write_column = weight_write && weight_index[9:7] == lane;
            wire [9:0] weight_address = write_column ?
                {weight_index[12:10], weight_index[6:0]} : {group_index, k_pair};
            always @(posedge clk)
                if (bias_write && bias_index[2:0] == lane)
                    biases[bias_index[5:3]] <= bias_data;
            for (parity = 0; parity < 2; parity = parity + 1) begin: weight_banks
                wire [15:0] weight;
                kwt_sram16 #(.AW(10)) memory(.clk(clk), .cs(write_column || operands_read),
                    .we(write_column), .addr(weight_address), .din(weight_data[parity*16+:16]),
                    .dout(weight));
                kwt_mac40 mac(.clk(clk), .rst_n(rst_n), .init(state == PRIME),
                    .enable(mac_enable), .x(activation[parity]), .w(weight),
                    .bias(parity == 0 ? biases[group_index] : 32'd0), .acc(accumulators[parity]));
            end
            always @(posedge clk)
                if (state == MERGE)
                    sums[lane] <= accumulators[0] + accumulators[1];
        end
    endgenerate

    if(OVERLAP) begin: page_control
        always @(posedge clk) begin
            if(!rst_n || clear) begin
                fill_page<=0;compute_page<=0;tile_full<=0;
            end else begin
                if(tile_end) begin tile_full[fill_page]<=1;fill_page<=!fill_page;end
                if(tile_consumed) begin tile_full[compute_page]<=0;compute_page<=!compute_page;end
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= FILL;
            rows_seen <= 0;
            fill_feature <= 0;
            fill_row <= 0;
            compute_row <= 0;
            tile_last_row <= 0;
            final_tile <= 0;
            group_index <= 0;
            k_pair <= 0;
            output_lane <= 0;
        end else if (clear) begin
            state <= FILL;
            rows_seen <= 0;
            fill_feature <= 0;
            fill_row <= 0;
            compute_row <= 0;
            group_index <= 0;
            k_pair <= 0;
            output_lane <= 0;
        end else begin
            if(fill) begin
                fill_feature<=fill_feature+1'b1;
                if(fill_feature==255) begin
                    rows_seen<=rows_seen+1'b1;
                    fill_row<=fill_row+1'b1;
                end
            end
            case(state)
            FILL: if(OVERLAP ? tile_full[compute_page] : tile_end) begin
                tile_last_row<=OVERLAP ? ((rows_seen==99 && fill_page!=compute_page) ? 3'd2 : 3'd7) : fill_row;
                final_tile<=OVERLAP ? rows_seen==99 && fill_page!=compute_page : rows_seen==98;
                compute_row<=0;
                state<=PRIME;
            end
            PRIME: begin
                k_pair <= 1;
                state <= MAC;
            end
            MAC: begin
                k_pair <= k_pair + 1'b1;
                if (k_pair == 127)
                    state <= LAST;
            end
            LAST: state <= MERGE;
            MERGE: begin
                output_lane <= 0;
                state <= SEND;
            end
            SEND: if (output_ready) begin
                output_lane <= output_lane + 1'b1;
                if (output_lane == 7) begin
                    group_index <= group_index + 1'b1;
                    state <= PRIME;
                    if (group_index == 7) begin
                        compute_row <= compute_row + 1'b1;
                        if (compute_row == tile_last_row) begin
                            compute_row <= 0;
                            state <= final_tile ? COMPLETE : FILL;
                        end
                    end
                end
            end
            default: state <= COMPLETE;
        endcase
        end
    end
endmodule
