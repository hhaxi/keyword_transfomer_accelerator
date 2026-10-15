`timescale 1ns/1ps
module tb_ffn_edges;
    reg clk=0; always #3.333 clk=~clk;
    reg rst_n=0,load_valid=0,start=0,clear=0;
    reg [19:0] load_addr=0;
    reg [31:0] load_data=0;
    wire load_ready,valid,done,fault;
    wire [63:0] data;
    wire [31:0] elapsed,mac_cycles,fifo_wait,second_mac,gelu_cycles,saturation;
    wire unused_ready,unused_valid,unused_error;
    wire [31:0] unused_data;
    integer cycles=0,n=0,c=0,j=0;
    wire ready=cycles%11!=0 && cycles%11!=1;
    reg [31:0] x[0:3167],w[0:8191],b[0:255],w2[0:8191],b2[0:63],sat[0:0];
    reg [63:0] expected[0:6335];
    string base;
    kwt_accel dut(.clk(clk),.rst_n(rst_n),.cmd_valid(1'b0),.cmd_ready(unused_ready),
        .cmd_addr(20'd0),.cmd_read(1'b0),.cmd_wdata(32'd0),.cmd_wmask(4'd0),
        .rsp_valid(unused_valid),.rsp_ready(1'b1),.rsp_rdata(unused_data),.rsp_err(unused_error),
        .dma_mode(1'b1),.dma_load_valid(load_valid),.dma_load_addr(load_addr),
        .dma_load_data(load_data),.dma_load_ready(load_ready),.dma_start(start),.dma_clear(clear),
        .ffn_mode(1'b1),.gelu_input_shift(5'd0),.gelu_output_shift(5'd0),
        .dma_out_valid(valid),.dma_out_data(data),.dma_out_ready(ready),.dma_done(done),.dma_fault(fault),
        .perf_cycles(elapsed),.perf_mac_cycles(mac_cycles),.perf_fifo_wait(fifo_wait),
        .perf_second_mac(second_mac),.perf_gelu(gelu_cycles),.perf_saturation(saturation));
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>1500000) $fatal(1,"Edge test timeout");
        if(rst_n && !clear) begin
            if(fault) $fatal(1,"Core fault");
            if(valid && ready) begin
                if(n>=6336 || data!==expected[n])
                    $fatal(1,"Edge mismatch case=%0d index=%0d got=%h expected=%h",c,n,data,expected[n]);
                n=n+1;
            end
        end
    end
    task automatic load(input [19:0] addr,input [31:0] value);
        begin
            @(negedge clk);load_valid=1;load_addr=addr;load_data=value;
            @(posedge clk);if(!load_ready) $fatal(1,"Load rejected");
        end
    endtask
    initial begin
        repeat(4) @(negedge clk);rst_n=1;
        for(c=0;c<3;c=c+1) begin
            @(negedge clk);clear=1;n=0;
            @(negedge clk);clear=0;
            base=$sformatf("output/ffn-edges/case_%0d/",c);
            $readmemh({base,"x.hex"},x);$readmemh({base,"w.hex"},w);$readmemh({base,"b.hex"},b);
            $readmemh({base,"w2.hex"},w2);$readmemh({base,"b2.hex"},b2);
            $readmemh({base,"expected.hex"},expected);$readmemh({base,"sat.hex"},sat);
            for(j=0;j<3168;j=j+1) load(20'h10000+20'(8*j),x[j]);
            for(j=0;j<8192;j=j+1) load(20'h20000+20'(8*j),w[j]);
            for(j=0;j<256;j=j+1) load(20'h30000+20'(4*j),b[j]);
            for(j=0;j<8192;j=j+1) load(20'h40000+20'(8*j),w2[j]);
            for(j=0;j<64;j=j+1) load(20'h50000+20'(4*j),b2[j]);
            @(negedge clk);load_valid=0;start=1;
            @(negedge clk);start=0;
            while(!done) @(negedge clk);
            if(n!=6336 || saturation!==sat[0] || mac_cycles!=202752 || second_mac!=101376 || gelu_cycles!=25344)
                $fatal(1,"Edge count mismatch case=%0d",c);
            $display("FFN_EDGE_CASE_PASS case=%0d outputs=%0d saturation=%0d",c,n,saturation);
        end
        $display("FFN_EDGES_PASS cases=3");$finish;
    end
endmodule
