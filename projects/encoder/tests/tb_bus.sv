`timescale 1ns/1ps
module tb_bus #(parameter integer DMA_BURST=1, HOST_BURST=0);
    reg clk=0;always #3.333 clk=~clk;
    reg rst_n=0,allow_a=1,pattern_stalls=0,check_fair=0;
    reg [2:0] run_mask=0,rr=7;
    wire [2:0] v,r,rv,err;
    // Packed master buses keep simulator change tracking explicit across
    // procedural scenario updates and flattened gate-level port connections.
    wire [2:0][31:0] data,addr;
    reg [2:0][31:0] base;
    integer issued[0:2],received[0:2],missed[0:2];
    integer max_missed[0:2],wait_age[0:2],max_wait[0:2];
    integer target=128,cycles=0,start_cycle,i,streak=0,max_streak=0;
    integer host_gap=0,host_pause=0;
    reg [2:0] was_stalled=0;reg [32:0] held[0:2];
    wire a_valid,a_ready,a_read,a_rsp_ready,ram_cs,ram_we;
    wire [19:0] a_addr;wire [31:0] a_wdata;wire [3:0] a_mask;
    reg a_rsp_valid=0;reg [31:0] a_rdata=0;reg a_err=0;
    wire [16:0] ram_addr;wire [3:0] ram_mask;wire [31:0] ram_wdata,ram_rdata;
    genvar g;
    generate for(g=0;g<3;g=g+1) begin
        assign v[g]=run_mask[g] && issued[g]<target && (g!=1 || host_pause==0);
        assign addr[g]=base[g]+32'(issued[g]*4);
    end endgenerate
    assign a_ready=allow_a && (!a_rsp_valid || a_rsp_ready);
    kwt_bus_fabric #(.DMA_BURST(DMA_BURST),.HOST_BURST(HOST_BURST)) dut(.clk(clk),.rst_n(rst_n),
        .c_valid(v[0]),.c_ready(r[0]),.c_addr(addr[0]),.c_wdata(32'b0),.c_read(1'b1),.c_mask(4'hf),
        .c_rsp_valid(rv[0]),.c_rsp_ready(rr[0]),.c_rdata(data[0]),.c_err(err[0]),
        .h_valid(v[1]),.h_ready(r[1]),.h_addr(addr[1]),.h_wdata(32'b0),.h_read(1'b1),.h_mask(4'hf),
        .h_rsp_valid(rv[1]),.h_rsp_ready(rr[1]),.h_rdata(data[1]),.h_err(err[1]),
        .d_valid(v[2]),.d_ready(r[2]),.d_addr(addr[2]),.d_wdata(32'b0),.d_read(1'b1),.d_mask(4'hf),
        .d_rsp_valid(rv[2]),.d_rsp_ready(rr[2]),.d_rdata(data[2]),.d_err(err[2]),.*);
    kwt_shared_sram ram(.clk(clk),.cs(ram_cs),.we(ram_we),.addr(ram_addr),.mask(ram_mask),.din(ram_wdata),.dout(ram_rdata));
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>30000) $fatal(1,"Bus timeout");
        if(!rst_n) begin
            host_pause<=0;
            a_rsp_valid<=0;was_stalled<=0;streak<=0;max_streak<=0;
            for(integer n=0;n<3;n=n+1) begin
                issued[n]<=0;received[n]<=0;missed[n]<=0;
                max_missed[n]<=0;wait_age[n]<=0;max_wait[n]<=0;
            end
        end else begin
            if(v[1] && r[1]) host_pause<=host_gap;
            else if(host_pause>0) host_pause<=host_pause-1;
            if(a_rsp_valid && a_rsp_ready) a_rsp_valid<=0;
            if(a_valid && a_ready) begin a_rsp_valid<=1;a_rdata<=32'hc0decafe;a_err<=0;end
            if((v&r)!=0) begin
                streak<=streak+1;if(streak+1>max_streak) max_streak<=streak+1;
            end else streak<=0;
            if(rv!=0 && rv!=1 && rv!=2 && rv!=4) $fatal(1,"Response has multiple owners");
            for(integer n=0;n<3;n=n+1) begin
                if(was_stalled[n] && (!rv[n] || {err[n],data[n]}!==held[n])) $fatal(1,"Response changed under stall");
                was_stalled[n]<=rv[n] && !rr[n];held[n]<={err[n],data[n]};
                if(v[n] && !r[n]) begin
                    wait_age[n]<=wait_age[n]+1;
                    if(wait_age[n]+1>max_wait[n]) max_wait[n]<=wait_age[n]+1;
                end else wait_age[n]<=0;
                if(v[n] && r[n]) begin issued[n]<=issued[n]+1;missed[n]<=0;end
                else if(v[n] && (v&r)!=0) begin
                    missed[n]<=missed[n]+1;
                    if(missed[n]+1>max_missed[n]) max_missed[n]<=missed[n]+1;
                    if(check_fair && missed[n]>=(n==0 ? DMA_BURST+(HOST_BURST>0 ? HOST_BURST : 1) :
                        n==1 ? DMA_BURST+1 : (HOST_BURST>0 ? 2*HOST_BURST+1 : 2))) $fatal(1,"Weighted round-robin starvation master=%0d missed=%0d grant=%0d next=%0d host_turn=%0d dma_turn=%0d",n,missed[n],dut.grant,dut.next_owner,dut.host_turn,dut.dma_turn);
                end
                if(rv[n] && rr[n]) begin
                    if(received[n]>=issued[n]) $fatal(1,"Unrequested response");
                    received[n]<=received[n]+1;
                    if(base[n]>=32'ha0010000 && base[n]<32'ha0080000) begin
                        if(err[n] || data[n]!==32'h50000000+32'(n*1024+received[n]))
                            $fatal(1,"RAM ownership/data mismatch owner=%0d index=%0d actual=%h error=%b ram_addr=%h ram_data=%h",n,received[n],data[n],err[n],ram_addr,ram_rdata);
                    end else if(n==0 && base[n]==32'h40000040) begin
                        if(err[n] || data[n]!==32'hc0decafe) $fatal(1,"Register routing mismatch");
                    end else if(!err[n]) $fatal(1,"Missing address protection error");
                end
            end
        end
    end
    always @(negedge clk) if(pattern_stalls)
        rr={cycles%17>5,cycles%11>3,cycles%13>4};
    task automatic reset_bus;
        begin
            @(negedge clk);run_mask=0;pattern_stalls=0;check_fair=0;rr=7;allow_a=1;rst_n=0;host_gap=0;
            repeat(4) @(negedge clk);rst_n=1;
            for(integer n=0;n<3;n=n+1) base[n]=32'ha0010000+32'(n*4096);
        end
    endtask
    task automatic wait_all;
        begin
            while((run_mask[0] && received[0]<target) || (run_mask[1] && received[1]<target) ||
                  (run_mask[2] && received[2]<target)) @(negedge clk);
            run_mask=0;
            if(check_fair) for(integer n=0;n<3;n++)
                $display("BUS_FAIR_PASS burst=%0d host_burst=%0d patterned=%0d gap=%0d master=%0d max_bypasses=%0d max_wait=%0d",DMA_BURST,HOST_BURST,pattern_stalls,host_gap,n,max_missed[n],max_wait[n]);
        end
    endtask
    initial begin
        for(i=0;i<3;i=i+1) for(integer j=0;j<128;j=j+1)
            ram.mem[16384+i*1024+j]=32'h50000000+32'(i*1024+j);
        reset_bus();start_cycle=cycles;run_mask=4;wait_all();
        if(cycles-start_cycle!=129 || max_streak!=128) $fatal(1,"Continuous-transfer bubble");
        $display("BUS_THROUGHPUT_PASS requests=128 cycles=129 consecutive_accepts=128");
        reset_bus();run_mask=7;check_fair=1;wait_all();
        if(max_streak!=384) $fatal(1,"Arbitration inserted bubbles");
        reset_bus();pattern_stalls=1;run_mask=7;check_fair=1;wait_all();
        if($test$plusargs("host_gaps")) for(integer gap=1;gap<=16;gap=gap*4) begin
            reset_bus();host_gap=gap;pattern_stalls=1;run_mask=7;check_fair=1;wait_all();
        end
        reset_bus();target=1;allow_a=0;base[0]=32'h40000040;run_mask=1;
        while(!a_valid) @(negedge clk);
        @(negedge clk);run_mask=7;
        repeat(8) begin
            @(negedge clk);
            if(!a_valid || a_addr!==20'h40 || (v&r)!=0) $fatal(1,"Target-stalled grant not held");
        end
        allow_a=1;wait_all();
        reset_bus();target=1;base[0]=32'hf0000000;base[1]=32'h40000040;base[2]=32'ha0000000;
        run_mask=7;wait_all();
        reset_bus();target=1;rr=0;run_mask=4;while(!rv[2]) @(negedge clk);
        reset_bus();repeat(5) begin @(negedge clk);if(rv!=0) $fatal(1,"Stale response after reset");end
        $display("BUS_PASS continuous transfers, fair arbitration, response stalls, locked grants, address protection, reset");
        $finish;
    end
endmodule
