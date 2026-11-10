`timescale 1ns/1ps
// Interface fixtures verify logical edge/latency behavior, not foundry timing.
module sram_gate_check #(parameter AW=7)(output reg done=0);
    reg clk=0;
    always #5 clk=~clk;
    reg cs=0,we=0;
    reg [AW-1:0] addr=0;
    reg [15:0] din=0;
    reg registered_drive=0,next_cs=0,next_we=0;
    reg [AW-1:0] next_addr=0;
    reg [15:0] next_din=0;
    always @(posedge clk) if(registered_drive) begin
        cs<=next_cs; we<=next_we; addr<=next_addr; din<=next_din;
    end
    wire [15:0] gated_q,plain_q;
`ifdef KWT_TEST_PRE_GATE_API
    kwt_sram16 #(.AW(AW)) dut(
`else
    kwt_sram16 #(.AW(AW),.GATE_CLK(1)) dut(
`endif
        .clk(clk),.cs(cs),.we(we),.addr(addr),.din(din),.dout(gated_q));
    // No GATE_CLK override: shared SRAM / TCM retain the original clock.
    kwt_sram16 #(.AW(AW)) default_dut(
        .clk(clk),.cs(cs),.we(we),.addr(addr),.din(din),.dout(plain_q));
    wire gated_clk,plain_clk;
    generate
        if(AW==7) begin
            assign gated_clk=dut.native128.u_macro.CLK;
            assign plain_clk=default_dut.native128.u_macro.CLK;
        end else if(AW==10) begin
            assign gated_clk=dut.native1024.u_macro.CLK;
            assign plain_clk=default_dut.native1024.u_macro.CLK;
        end else begin
            assign gated_clk=dut.native4096.u_macro.CLK;
            assign plain_clk=default_dut.native4096.u_macro.CLK;
        end
    endgenerate
    integer gated_edges=0,plain_edges=0,errors=0,saved_edges,i;
    reg edge_checks=0;
    time last_rise=0;
    task check(input bit condition,input string reason);
        if(!condition) begin
            errors=errors+1;
            $display("SRAM_GATE_FAIL AW=%0d time=%0t %s",AW,$time,reason);
        end
    endtask
    always @(posedge gated_clk) begin
        gated_edges=gated_edges+1;
        if($test$plusargs("debug") && AW==7 && $time<40)
            $display("GATE_DEBUG time=%0t clk=%b cs=%b gated=%b",$time,clk,cs,gated_clk);
        last_rise=$time;
        if(edge_checks) check(clk===1'b1 && ($time%10)==5,
                              "clock rose away from source rising edge");
    end
    always @(negedge gated_clk) if(edge_checks && last_rise!=0)
        check(($time-last_rise)==5,"clock high pulse was truncated");
    always @(posedge plain_clk) plain_edges=plain_edges+1;
    task tick;
        @(posedge clk); #1;
    endtask
    task low;
        @(negedge clk); #1;
    endtask
    task expect_q(input [15:0] expected,input string reason);
        check(gated_q===expected,reason);
        check(gated_q===plain_q,"gated/default read data differ");
    endtask
    initial begin
        #1; edge_checks=1;
        repeat(3) tick();
        check(gated_edges==0,"idle SRAM received clock edges");
        check(plain_edges==3,"default SRAM clock changed");

        // A high-phase CS pulse must not manufacture an SRAM clock edge.
        saved_edges=gated_edges;
        #1; cs=1; we=1; din=16'hdead; addr=3;
        #1; cs=0;
        #1; check(gated_edges==saved_edges,"high-phase CS glitch generated an edge");
        low();
        // Low-phase enable which disappears before the edge is not an access.
        cs=1; #1; cs=0;
        tick();
        check(gated_edges==saved_edges,"cancelled low-phase request generated an edge");

        // CS can fall during the high phase without cutting the clock pulse.
        low(); cs=1; we=1; addr=1; din=16'h1234;
        tick(); #1; cs=0;
        #1; check(gated_clk===1'b1,"CS fall truncated an active clock pulse");
        low();
        // Change address/data immediately after each edge, as source flops do.
        cs=1; we=1; addr=2; din=16'habcd;
        tick(); we=0; addr=1; din=16'hffff;
        tick(); expect_q(16'h1234,"read did not return on its request edge");
        addr=2;
        #1; expect_q(16'h1234,"read output changed before next rising edge");
        tick(); expect_q(16'habcd,"back-to-back read gained an extra cycle");

        // Output is held during inactive clocks despite changing address/data.
        low(); cs=0; we=1; addr=1; din=16'hffff;
        saved_edges=gated_edges;
        repeat(4) begin tick(); expect_q(16'habcd,"idle changed read output"); end
        check(gated_edges==saved_edges,"inactive bank clock did not stop");
        low(); cs=1; we=0; addr=1;
        tick(); expect_q(16'h1234,"idle write controls corrupted stored data");

        // Deterministic pseudo-random active/idle traffic and dense alternation.
        for(i=0;i<96;i=i+1) begin
            low(); cs=((i%5)!=0); we=1; addr=AW'(i+16); din=16'(i*997+AW);
            tick();
            low(); cs=1; we=0; addr=AW'(i+16);
            tick();
            if((i%5)!=0) expect_q(16'(i*997+AW),"write/read equivalence failure");
            else check(gated_q===plain_q,"inactive-write traffic differs from default");
        end
        // Source-flop NBA updates at the root edge must not race the gated
        // macro edge: current request is sampled before the next request.
        low(); cs=1; we=0; addr=2;
        tick(); expect_q(16'habcd,"prepare registered-source hold check");
        low(); cs=1; we=1; addr=5; din=16'h4321;
        registered_drive=1; next_cs=1; next_we=0; next_addr=5;
        tick(); expect_q(16'habcd,"write unexpectedly changed read output");
        next_cs=0;
        tick(); expect_q(16'h4321,"NBA source controls changed read latency");
        saved_edges=gated_edges;
        next_cs=1; next_addr=2;
        tick(); expect_q(16'h4321,"new request leaked through disabled clock high phase");
        check(gated_edges==saved_edges,"NBA enable created an extra gated edge");
        next_cs=0;
        tick(); expect_q(16'habcd,"registered request did not return on the next edge");
        low(); registered_drive=0; cs=0;
        repeat(2) tick();
        if(errors) $fatal(1,"SRAM_GATE AW=%0d errors=%0d",AW,errors);
        $display("SRAM_GATE_PASS AW=%0d gated_edges=%0d default_edges=%0d",AW,gated_edges,plain_edges);
        done=1;
    end
endmodule
module tb_sram_gate;
    wire d128,d1024,d4096;
    sram_gate_check #(.AW(7)) c128(d128);
    sram_gate_check #(.AW(10)) c1024(d1024);
    sram_gate_check #(.AW(12)) c4096(d4096);
    initial begin wait(d128 && d1024 && d4096); $display("SRAM_GATE_ALL_PASS"); $finish; end
    initial begin #10000; $fatal(1,"SRAM gate timeout"); end
endmodule
