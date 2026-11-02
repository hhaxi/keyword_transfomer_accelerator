`timescale 1ns/1ps
// Contract test: first-row execution before the other 98 rows exist locally.
module tb_stream;
    reg clk=0; always #3.333 clk=~clk;
    reg rst_n=0,dma_load_valid=0,dma_start=0,dma_clear=0;
    reg [19:0] dma_load_addr=0; reg [31:0] dma_load_data=0;
    wire dma_load_ready,dma_out_valid,dma_done,dma_fault;
    wire [1:0] dma_x_free;
    wire [63:0] dma_out_data; wire [31:0] perf_cycles,perf_mac_cycles,perf_fifo_wait;
    integer cycles=0,outputs=0,stall_left=0,j,r,taskid=0;
    string folder;
    wire dma_out_ready=cycles%11!=0 && stall_left==0;
    reg [31:0] x[0:3167],w[0:8191],b[0:255];
    reg [63:0] expected[0:25343];
    kwt_ffn1_core dut(.*);
    always @(posedge clk) if(rst_n) begin
        cycles<=cycles+1;
        if(stall_left>0) stall_left<=stall_left-1;
        if(cycles==20000) stall_left<=400;
        if(cycles>300000) $fatal(1,"Stream timeout");
        if(dma_out_valid && dma_out_ready) begin
            if(dma_out_data!==expected[outputs]) $fatal(1,"Stream result mismatch %0d",outputs);
            outputs<=outputs+1;
        end
    end
    task automatic load(input [19:0] addr,input [31:0] data);
        begin
            @(negedge clk);dma_load_valid=1;dma_load_addr=addr;dma_load_data=data;
            @(posedge clk);if(!dma_load_ready) $fatal(1,"Unexpected load backpressure");
            @(negedge clk);dma_load_valid=0;
        end
    endtask
    initial begin
        if($value$plusargs("task=%d",taskid)) begin end
        folder=$sformatf("vectors/task_%02d",taskid);
        $readmemh({folder,"/x_packed.hex"},x);$readmemh({folder,"/w_packed.hex"},w);
        $readmemh({folder,"/b.hex"},b);$readmemh({folder,"/expected.hex"},expected);
        repeat(4) @(negedge clk);rst_n=1;
        for(j=0;j<8192;j=j+1) load(20'h20000+20'(j*8),w[j]);
        for(j=0;j<256;j=j+1) load(20'h30000+20'(j*4),b[j]);
        for(j=0;j<32;j=j+1) load(20'h10000+20'(j*8),x[j]);
        @(negedge clk);dma_start=1;@(negedge clk);dma_start=0;
        repeat(100) @(negedge clk);
        if(outputs==0 || dma_fault) $fatal(1,"Missing row streaming: requires all 99 X rows before execution");
        // Deliberately late row1 forces the compute core to wait safely.
        if(!$test$plusargs("early_next")) repeat(1200) @(negedge clk);
        for(r=1;r<99;r=r+1) begin
            if(r>=2) while(outputs<(r-1)*256) @(negedge clk);
            for(j=0;j<32;j=j+1) load(20'h10000+20'((r*32+j)*8),x[r*32+j]);
        end
        while(!dma_done) @(negedge clk);
        if(outputs!=25344 || dma_fault || perf_mac_cycles!=101376) $fatal(1,"Stream completion/count mismatch");
        $display("STREAM_PASS 99 rows, parity ping-pong, late row, FIFO stalls, exact outputs");$finish;
    end
endmodule
