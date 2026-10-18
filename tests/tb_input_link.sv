`timescale 1ns/1ps
// Actual linked engines and shared single-port SRAM; no CPU timing claims here.
module tb_input_link #(parameter integer DMA_BURST=1, HOST_BURST=0, BACKGROUND_HOST=0);
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,h_valid=0,h_read=0,h_rsp_ready=1;
    reg [31:0] h_addr=0,h_wdata=0;wire [3:0] h_mask=15;
    wire h_ready,h_rsp_valid,h_err;wire [31:0] h_rdata;
    wire c_ready,c_rsp_valid,c_err;wire [31:0] c_rdata;
    reg bg_run=1,bg_ready=1,bg_held=0;
    wire bg_valid=BACKGROUND_HOST!=0 && rst_n && bg_run;
    integer bg_sent=0,bg_received=0,bg_wait=0,bg_max_wait=0,bg_stalls=0;
    kwt_extended_system_bus #(.DMA_BURST(DMA_BURST),.HOST_BURST(HOST_BURST)) dut(.clk(clk),.rst_n(rst_n),
        .c_valid(h_valid),.c_addr(h_addr),.c_wdata(h_wdata),.c_read(h_read),.c_mask(h_mask),.c_rsp_ready(h_rsp_ready),
        .c_ready(h_ready),.c_rsp_valid(h_rsp_valid),.c_rdata(h_rdata),.c_err(h_err),
        .h_valid(bg_valid),.h_addr(32'ha007f000),.h_wdata(32'd0),.h_read(1'b1),.h_mask(4'hf),.h_rsp_ready(bg_ready),
        .h_ready(c_ready),.h_rsp_valid(c_rsp_valid),.h_rdata(c_rdata),.h_err(c_err));
    reg [31:0] x[0:6335],params[0:16703],w1[0:8191],w2[0:8191],b1[0:255],b2[0:63],cfg[0:1];
    reg [31:0] packed_x[0:3167],expected[0:6335],rd;reg [63:0] ffn_expected[0:6335];
    integer cycle=0,j,trial,in_count=0,out_count=0,full_wait=0,simultaneous=0,peak=0;
    reg held=0;reg [31:0] held_data;
    always @(negedge clk) bg_ready=BACKGROUND_HOST==0 || cycle%11>3;
    always @(posedge clk) if(rst_n && BACKGROUND_HOST!=0) begin
        if(bg_held && (!c_rsp_valid || c_err || c_rdata!==32'h51a7cafe)) $fatal(1,"Background response changed");
        bg_held=c_rsp_valid && !bg_ready;
        if(bg_held) bg_stalls++;
        if(bg_valid && c_ready) bg_sent++;
        if(c_rsp_valid && bg_ready) begin
            if(c_err || c_rdata!==32'h51a7cafe || bg_received>=bg_sent) $fatal(1,"Background response ownership");
            bg_received++;
        end
        if(bg_valid && !c_ready) begin bg_wait++;if(bg_wait>bg_max_wait) bg_max_wait=bg_wait;end
        else bg_wait=0;
    end
    always @(posedge clk) begin
        cycle++;
        if(cycle>8000000) $fatal(1,"Linked timeout");
        if(rst_n) begin
            if(dut.ffn_abort || dut.enc_abort) held=0;
            else begin
                if(held && (!dut.input_valid || dut.input_data!==held_data)) $fatal(1,"Linked held data");
                held=dut.input_valid && !dut.input_ready;held_data=dut.input_data;
                if(held) full_wait++;
                if(dut.feed_valid && dut.feed_ready) begin
                    if(dut.feed_data!==packed_x[in_count]) $fatal(1,"Linked input order");
                    in_count++;
                end
                if(dut.result_valid && dut.result_ready) begin
                    if({{24{dut.result_data[39]}},dut.result_data}!==ffn_expected[out_count]) $fatal(1,"Linked FFN order");
                    out_count++;
                end
            end
            if(dut.input_fifo.push && dut.input_fifo.pop) simultaneous++;
            if(integer'(dut.input_fifo.count)>peak) peak=integer'(dut.input_fifo.count);
            if(dut.accelerator.core.xwrite && dut.accelerator.core.read_operands && !dut.accelerator.core.second_stage) $fatal(1,"Linked X collision");
        end
    end
    task automatic bus(input bit read_,input [31:0] addr,input [31:0] value);
        begin
            @(negedge clk);h_valid=1;h_read=read_;h_addr=addr;h_wdata=value;
            do @(posedge clk);while(!h_ready);
            @(negedge clk);h_valid=0;
            while(!h_rsp_valid) @(negedge clk);
            if(h_err) $fatal(1,"Linked register error %h",addr);
            rd=h_rdata;@(negedge clk);
        end
    endtask
    task automatic start_pair;
        begin
            in_count=0;out_count=0;
            bus(0,32'h40000000,2);bus(0,32'h40080000,4);
            bus(0,32'h40080038,0);bus(0,32'h40000000,1);bus(0,32'h40080000,1);
        end
    endtask
    task automatic check_cancel;
        begin
            while(dut.accelerator.active || dut.encoder.busy) @(negedge clk);
            repeat(4) @(negedge clk);
            if(dut.input_fifo.count || dut.result_fifo.count || dut.encoder.z_valid || dut.encoder.resident_valid ||
                dut.accelerator.core.nx || dut.accelerator.outstanding_count || dut.encoder.pending_count || dut.f_valid || dut.e_valid)
                $fatal(1,"Linked cancellation retained state/requests");
            $display("INPUT_LINK_CANCEL_PASS phase=%0d words=%0d",trial,in_count);
        end
    endtask
    initial begin
        dut.shared.mem[130048]=32'h51a7cafe;
        $readmemh("output/encoder-vectors/task_00/input.hex",x);
        $readmemh("output/encoder-vectors/task_00/layer_00/ffn_input.hex",packed_x);
        $readmemh("output/encoder-vectors/task_00/layer_00/ffn.hex",ffn_expected);
        $readmemh("output/encoder-vectors/task_00/layer_00/expected.hex",expected);
        $readmemh("output/encoder-vectors/layer_00/params.hex",params);
        $readmemh("output/encoder-vectors/layer_00/w1.hex",w1);$readmemh("output/encoder-vectors/layer_00/w2.hex",w2);
        $readmemh("output/encoder-vectors/layer_00/b1.hex",b1);$readmemh("output/encoder-vectors/layer_00/b2.hex",b2);
        $readmemh("output/encoder-vectors/layer_00/config.hex",cfg);
        for(j=0;j<6336;j++) dut.shared.mem[16384+j]=x[j];
        for(j=0;j<16704;j++) dut.shared.mem[81920+j]=params[j];
        for(j=0;j<8192;j++) begin dut.shared.mem[32768+j]=w1[j];dut.shared.mem[65536+j]=w2[j];end
        for(j=0;j<256;j++) dut.shared.mem[40960+j]=b1[j];
        for(j=0;j<64;j++) dut.shared.mem[73728+j]=b2[j];
        repeat(4) @(negedge clk);rst_n=1;
        bus(0,32'h40000020,32'ha0018000);bus(0,32'h40000024,32'ha0020000);bus(0,32'h40000028,32'ha0028000);
        bus(0,32'h4000002c,32'ha0030000);bus(0,32'h40000030,32'ha0040000);bus(0,32'h40000034,32'ha0048000);
        bus(0,32'h40000038,4);bus(0,32'h4000003c,cfg[0]);
        bus(0,32'h40080020,32'ha0010000);bus(0,32'h40080024,32'ha0050000);bus(0,32'h40080028,32'ha0018000);
        bus(0,32'h4008002c,32'ha0030000);bus(0,32'h40080030,32'ha0064000);bus(0,32'h40080034,cfg[1]|24);
        for(trial=0;trial<3;trial++) begin
            start_pair();
            if(trial==0) begin
                while(dut.accelerator.read_received<20) @(negedge clk);
                bus(0,32'h40000000,2);
            end else if(trial==1) begin
                while(!(dut.input_valid && !dut.input_ready && dut.accelerator.input_words>=256)) @(negedge clk);
                bus(0,32'h40080000,2);
            end else begin
                while(!dut.encoder.done || dut.encoder.busy || dut.result_fifo.count!=4) @(negedge clk);
                bus(0,32'h40080000,2);
            end
            check_cancel();
        end
        start_pair();while(!dut.encoder.done || dut.encoder.busy) @(negedge clk);
        bus(0,32'h40080038,1);bus(0,32'h40080000,1);
        while(!dut.encoder.done || dut.encoder.busy || dut.accelerator.active) @(negedge clk);
        if(!dut.accelerator.done || dut.accelerator.error || dut.encoder.error || in_count!=3168 || out_count!=6336) $fatal(1,"Linked restart status/count");
        for(j=0;j<6336;j++) if(dut.shared.mem[102400+j]!==expected[j]) $fatal(1,"Linked restart output %0d",j);
        if(peak!=4 || full_wait==0 || simultaneous==0) $fatal(1,"Linked FIFO coverage");
        $display("INPUT_LINK_PASS single_port cancellation_both_directions idle_front_cancel restart words=%0d outputs=%0d peak=%0d full_wait=%0d simultaneous=%0d",in_count,out_count,peak,full_wait,simultaneous);
        if(BACKGROUND_HOST!=0) begin
            do @(posedge clk);while(!c_ready);
            @(negedge clk);bg_run=0;
            while(bg_received!=bg_sent) @(negedge clk);
            if(bg_stalls==0 || bg_sent<1000) $fatal(1,"Background coverage");
            $display("HOST_BACKGROUND_PASS requests=%0d responses=%0d response_stalls=%0d max_wait=%0d",bg_sent,bg_received,bg_stalls,bg_max_wait);
        end
        $finish;
    end
endmodule
