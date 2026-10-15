`timescale 1ns/1ps
module tb_accel;
    reg clk=0; always #3.333 clk=~clk;
    reg rst_n=0,cmd_valid=0,cmd_read=0,rsp_ready=0;
    reg [19:0] cmd_addr=0;
    reg [31:0] cmd_wdata=0;
    reg [3:0] cmd_wmask=15;
    wire cmd_ready,rsp_valid,rsp_err;
    wire [31:0] rsp_rdata;
    reg [31:0] xv[0:6335],wv[0:16383],bv[0:255];
    reg [63:0] expected[0:25343];
    reg [31:0] rd,lo,hi,held;
    integer taskid,j,transactions=0,num_tasks=12;
    longint cycles=0,start_cycle;
    string folder;
    kwt_accel dut(.ffn_mode(1'b0),.gelu_input_shift(5'd0),.gelu_output_shift(5'd0),
        .perf_second_mac(),.perf_gelu(),.perf_saturation(),.dma_mode(1'b0),.dma_load_valid(1'b0),.dma_load_addr(20'b0),
        .dma_load_data(32'b0),.dma_load_ready(),.dma_start(1'b0),.dma_clear(1'b0),
        .dma_out_valid(),.dma_out_data(),.dma_out_ready(1'b0),.dma_done(),.dma_fault(),
        .perf_cycles(),.perf_mac_cycles(),.perf_fifo_wait(),.*);
    always @(posedge clk) begin cycles<=cycles+1; if(cycles>100000000) $fatal(1,"timeout"); end
    task automatic bus(input bit read_,input [19:0] addr_,input [31:0] data_,input bit error_,output [31:0] data_out);
        begin
            @(negedge clk); cmd_valid=1;cmd_read=read_;cmd_addr=addr_;cmd_wdata=data_;rsp_ready=0;
            do @(posedge clk); while(!cmd_ready);
            @(negedge clk); cmd_valid=0;
            while(!rsp_valid) @(negedge clk);
            held=rsp_rdata;
            if(transactions%97==0) begin
                repeat(3) begin @(negedge clk); if(!rsp_valid || rsp_rdata!==held || cmd_ready) $fatal(1,"unstable stalled response or extra acceptance"); end
            end
            data_out=rsp_rdata;
            if(rsp_err!==error_) $fatal(1,"bus error mismatch addr=%h expected=%b",addr_,error_);
            rsp_ready=1; @(negedge clk); rsp_ready=0; transactions=transactions+1;
        end
    endtask
    initial begin
        if($value$plusargs("tasks=%d",num_tasks)) begin end
        repeat(4) @(negedge clk);rst_n=1;
        bus(0,0,1,1,rd); // Incomplete parameters must not start.
        bus(1,20'h10,0,1,rd); // No result available.
        bus(0,0,2,0,rd);
        cmd_wmask=1; bus(0,20'h10000,0,1,rd); cmd_wmask=15;
        bus(0,0,2,0,rd);
        for(taskid=0;taskid<num_tasks;taskid=taskid+1) begin
            folder=$sformatf("output/vectors/task_%02d",taskid);
            $readmemh({folder,"/x.hex"},xv);$readmemh({folder,"/w.hex"},wv);
            $readmemh({folder,"/b.hex"},bv);$readmemh({folder,"/expected.hex"},expected);
            start_cycle=cycles;
            bus(0,0,2,0,rd);
            for(j=0;j<6336;j=j+1) bus(0,20'h10000+20'(j*4),xv[j],0,rd);
            for(j=0;j<16384;j=j+1) bus(0,20'h20000+20'(j*4),wv[j],0,rd);
            for(j=0;j<256;j=j+1) bus(0,20'h30000+20'(j*4),bv[j],0,rd);
            bus(0,0,1,0,rd);
            bus(0,0,1,1,rd); // Busy start must be rejected, ongoing work survives.
            bus(0,20'h10000,0,1,rd);
            // Stop consuming long enough to fill both FIFO groups and stall MAC.
            // Repeated low-half reads must preserve the oldest result.
            repeat(400) @(negedge clk);
            bus(1,4,0,0,rd);
            if (!rd[4] || !rd[2] || !rd[0] || rd[1]) $fatal(1,"queued group status mismatch");
            bus(1,20'h10,0,0,lo);
            repeat(200) @(negedge clk);
            bus(1,20'h10,0,0,hi);
            if (hi!==lo || lo!==expected[0][31:0]) $fatal(1,"FIFO head changed under backpressure");
            for(j=0;j<25344;j=j+1) begin
                rd=0;
                // Alternate legacy single-result polling and four-result batches.
                if(taskid%2==0) while(!rd[2]) bus(1,4,0,0,rd);
                else if(j%4==0) while(!rd[4]) bus(1,4,0,0,rd);
                bus(1,20'h10,0,0,lo); bus(1,20'h14,0,0,hi);
                if({hi,lo}!==expected[j]) $fatal(1,"task=%0d output=%0d actual=%h expected=%h",taskid,j,{hi,lo},expected[j]);
                if(j%1013==0) repeat(200) @(negedge clk);
            end
            bus(1,4,0,0,rd);
            if(rd[2:0]!==3'b010) $fatal(1,"completion status mismatch");
            $display("ACCEL_TASK_PASS task=%0d cycles=%0d outputs=25344",taskid,cycles-start_cycle);
            if(taskid==0) begin
                bus(0,0,1,0,rd);repeat(400) @(negedge clk);
                bus(0,0,2,0,rd);bus(1,4,0,0,rd);
                if(rd!==0) $fatal(1,"abort must discard queued outputs");
                bus(1,20'h10,0,1,rd);bus(0,0,1,1,rd);
            end
        end
        // Reset during a full output queue, without resetting SRAM payloads.
        // In the one-task run task 0 already invalidated parameters by abort.
        if(num_tasks>1) begin bus(0,0,1,0,rd);repeat(400) @(negedge clk);end
        rst_n=0;repeat(4) @(negedge clk);rst_n=1;
        bus(1,4,0,0,rd);if(rd!==0) $fatal(1,"reset failed");
        bus(0,0,1,1,rd);bus(1,20'h14,0,1,rd);
        $display("ACCEL_PASS %0d parameter sets, bit-exact outputs, FIFO stalls, scalar/batch reads, errors, abort, reset",num_tasks);$finish;
    end
endmodule
