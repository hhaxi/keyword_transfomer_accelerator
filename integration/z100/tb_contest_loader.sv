`timescale 1ns/1ps
module tb_contest_loader;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0,start=0, inject_error=0;
    reg [31:0] source=32'h10000ff0;
    reg [18:0] destination=19'h7ff00;
    reg [15:0] words=37;
    wire busy,fault,arvalid,rready,host_valid;
    wire [31:0] araddr;
    wire [7:0] arlen;
    wire [18:0] host_addr;
    reg [4:0] left=0;
    reg [31:0] read_address;
    reg [31:0] cycle=0;
    reg host_response=0;
    reg [31:0] accepted=0, bursts=0;
    wire arready=left==0 && cycle%3!=0;
    wire rvalid=left!=0 && cycle%5!=0;
    wire rlast=left==1;
    wire [31:0] rdata=read_address ^ 32'ha5a55a5a;
    wire [1:0] rresp=inject_error && left==3 ? 2'b10 : 2'b00;
    wire host_ready=cycle%4!=0;
    wire host_error=0;
    z100_contest_loader dut(.*);
    always @(posedge clk) begin
        cycle<=cycle+1;
        if(arvalid && arready) begin
            if(13'(araddr[11:0])+(({5'd0,arlen}+13'd1)<<2)>4096)
                $fatal(1,"AXI burst crosses page");
            left<=5'(arlen)+1'b1;
            read_address<=araddr;
            bursts<=bursts+1;
        end
        if(rvalid && rready) begin
            left<=left-1'b1;
            read_address<=read_address+4;
        end
        host_response<=host_valid && host_ready;
        if(host_valid && host_ready) begin
            if(host_addr!==19'(destination+accepted*4) ||
                rdata!==((source+accepted*4)^32'ha5a55a5a))
                $fatal(1,"Loader lost ordering or data under backpressure");
            accepted<=accepted+1;
        end
    end
    task automatic run_transfer;
        @(negedge clk);start=1;
        @(negedge clk);start=0;
        while(busy) @(negedge clk);
    endtask
    initial begin
        repeat(4) @(negedge clk);rst_n=1;
        run_transfer();
        if(fault || accepted!=37 || bursts!=4 || host_response) $fatal(1,"Initial burst transfer failed");
        words=65;
        run_transfer();
        if(!fault || bursts!=4) $fatal(1,"SRAM range violation escaped");
        accepted=0;words=37;inject_error=1;
        run_transfer();
        if(!fault || accepted>=37 || left!=0) $fatal(1,"AXI error did not drain");
        accepted=0;inject_error=0;
        run_transfer();
        if(fault || accepted!=37) $fatal(1,"Retry failed");
        $display("CONTEST_LOADER_PASS burst boundary, backpressure, range, AXI fault and retry");
        $finish;
    end
    initial #30000 $fatal(1,"Loader timed out");
endmodule
