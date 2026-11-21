`timescale 1ns/1ps
module tb_result_fifo;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,clear=0,in_valid=0,out_ready=0;
    reg [39:0] in_data=0;
    wire in_ready,out_valid;wire [39:0] out_data;
    reg [39:0] expected[0:20000];
    integer head=0,tail=0,cycle=0,pushed=0,popped=0,full_refill=0,stalls=0;
    reg held=0;reg [39:0] held_data;
    reg [31:0] random_state=32'hac20399;
    kwt_result_fifo dut(.*);
    always @(posedge clk) begin
        if(!rst_n || clear) begin head=0;tail=0;held=0;end
        else begin
            if(held && (!out_valid || out_data!==held_data)) $fatal(1,"Stalled FIFO output changed");
            held=out_valid && !out_ready;held_data=out_data;
            if(out_valid && !out_ready) stalls++;
            if(dut.count==4 && in_valid && in_ready && out_valid && out_ready) full_refill++;
            if(out_valid && out_ready) begin
                if(head==tail || out_data!==expected[head]) $fatal(1,"FIFO order/data mismatch");
                head++;popped++;
            end
            if(in_valid && in_ready) begin expected[tail]=in_data;tail++;pushed++;end
        end
    end
    initial begin
        repeat(4) @(negedge clk);rst_n=1;
        for(cycle=0;cycle<10000;cycle++) begin
            @(negedge clk);
            random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
            clear=cycle==4000;
            if(cycle==7000) rst_n=0;else rst_n=1;
            out_ready=cycle%100>20 && random_state[0];
            if(!in_valid || in_ready || clear || !rst_n) begin
                in_valid=random_state[1];in_data={random_state,8'(cycle)};
            end
        end
        @(negedge clk);in_valid=0;out_ready=1;
        repeat(8) @(negedge clk);
        if(out_valid || head!=tail || !full_refill || !stalls) $fatal(1,"FIFO coverage/drain failed");
        $display("RESULT_FIFO_PASS pushed=%0d popped=%0d full_refill=%0d stalls=%0d clear_reset",pushed,popped,full_refill,stalls);
        $finish;
    end
endmodule
