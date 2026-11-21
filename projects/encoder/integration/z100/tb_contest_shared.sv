`timescale 1ns/1ps
module tb_contest_shared;
    reg clk=0;
    always #5 clk=~clk;
    reg cs=0,we=0;
    reg [16:0] addr;
    reg [3:0] mask;
    reg [31:0] din;
    wire [31:0] dout;
    kwt_shared_sram dut(.*);

    task automatic write(input [16:0] address, input [31:0] value, input [3:0] lanes);
        @(negedge clk);
        cs=1;we=1;addr=address;din=value;mask=lanes;
    endtask

    task automatic check(input [16:0] address, input [31:0] expected);
        @(negedge clk);
        cs=1;we=0;addr=address;
        @(posedge clk);
        #1;
        if(dout!==expected) $fatal(1,"SRAM word %h expected %h got %h",address,expected,dout);
    endtask

    initial begin
        for(int bank=0;bank<128;bank++) begin
            write(17'(bank<<10),32'h55aa0000+bank,4'hf);
            write(17'((bank<<10)+1023),32'haa550000+bank,4'hf);
        end
        for(int bank=0;bank<128;bank++) begin
            check(17'(bank<<10),32'h55aa0000+bank);
            check(17'((bank<<10)+1023),32'haa550000+bank);
        end
        write(17'h1ffff,32'h11223344,4'b0101);
        check(17'h1ffff,32'haa220044);
        check(0,32'h55aa0000);
        @(negedge clk);cs=0;addr=17'h1ffff;
        repeat(2) @(negedge clk);
        if(dout!==32'h55aa0000) $fatal(1,"Inactive SRAM output changed");
        $display("CONTEST_SHARED_SRAM_PASS banks=128 bytes=524288 byte_mask=pass");
        $finish;
    end
endmodule
