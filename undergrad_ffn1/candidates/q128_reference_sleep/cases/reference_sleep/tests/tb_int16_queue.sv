`timescale 1ns/1ps
module tb_int16_queue;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, clear=0, in_valid=0, out_ready=0;
    reg [2559:0] values;
    reg [6:0] row;
    reg [7:0] col;
    reg [3:0] rows;
    wire in_ready, out_valid;
    wire [31:0] word;
    wire [14:0] index;
    kwt_int16_result_queue #(.ROWS(8),.COLS(8)) dut(
        .clk(clk),.rst_n(rst_n),.clear(clear),.in_valid(in_valid),.in_ready(in_ready),
        .in_values(values),.in_row(row),.in_col(col),.in_rows(rows),
        .out_valid(out_valid),.out_ready(out_ready),.out_word(word),.out_index(index));

    task automatic check_word(input [14:0] want_index, input [31:0] want_word);
        if (!out_valid || index !== want_index || word !== want_word)
            $fatal(1,"index=%d/%d word=%h/%h valid=%b",index,want_index,word,want_word,out_valid);
    endtask

    integer i;
    initial begin
        @(negedge clk); rst_n=1;
        values=0; row=96; col=248; rows=3; in_valid=1;
        values[ 0+:40]=40'sd16384;       // +0.5 -> 0
        values[40+:40]=40'sd49152;       // +1.5 -> 2
        values[80+:40]=-40'sd16384;      // -0.5 -> 0
        values[120+:40]=-40'sd49152;     // -1.5 -> -2
        values[160+:40]=40'sd549755813887;
        values[200+:40]=-40'sd549755813888;
        values[240+:40]=-40'sd773998647; // A real accumulator that clipped with shift 14.
        values[280+:40]=40'sd773998647;
        @(negedge clk); in_valid=0;
        repeat(3) begin
            check_word(15'd12412,32'h00020000);
            if(in_ready) $fatal(1,"full queue unexpectedly accepts a group");
            @(negedge clk);
        end
        out_ready=1;
        for(i=0;i<12;i=i+1) begin
            #1;
            case(i)
                0:check_word(15'd12412,32'h00020000);
                1:check_word(15'd12413,32'hfffe0000);
                2:check_word(15'd12414,32'h80007fff);
                3:check_word(15'd12415,{16'sd23621,-16'sd23621});
                default:check_word(15'(12412+(i/4)*128+(i%4)),0);
            endcase
            if(i==11) begin
                // The last old beat and first new group can handshake on the same edge.
                if(!in_ready) $fatal(1,"last beat did not release slot");
                in_valid=1; row=0; col=8; rows=8; values=0; values[0+:40]=40'sd32768;
            end
            @(negedge clk);
        end
        in_valid=0;
        check_word(15'd4,32'h00000001);
        clear=1;
        @(negedge clk); clear=0; out_ready=0; #1;
        if(out_valid || !in_ready) $fatal(1,"clear did not empty queue");
        $display("INT16_QUEUE_PASS");
        $finish;
    end
endmodule
