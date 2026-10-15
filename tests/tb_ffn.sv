`timescale 1ns/1ps
module tb_ffn;
    reg clk=0;always #3.333 clk=~clk;
    reg rst_n=0,cmd_valid=0,cmd_read=0,rsp_ready=0;
    reg [19:0] cmd_addr=0;reg [31:0] cmd_wdata=0;reg [3:0] cmd_wmask=15;
    wire cmd_ready,rsp_valid,rsp_err;wire [31:0] rsp_rdata;
    wire m_valid,m_read,m_rsp_ready;wire [31:0] m_addr,m_wdata;wire [3:0] m_mask;
    reg pending=0,pending_read=1,force_block=0;integer delay_left=0,fixed_delay=0,inject_kind=0;
    reg [31:0] m_rdata=0;reg m_err=0;
    wire m_rsp_valid=pending && delay_left==0;
    wire m_ready=(!pending || (m_rsp_valid && m_rsp_ready)) && !force_block && cycles%7!=0;
    reg [31:0] mem[0:131071],xv[0:6335],wv[0:16383],bv[0:255];
    reg [63:0] expected[0:6335],first_expected[0:25343];
    reg [31:0] w2p[0:8191],b2v[0:63],cfg[0:0];
    reg [31:0] rd,held,profile[0:14];
    integer j,polls,read_count=0,write_count=0,cycles=0,transactions=0;
    reg was_stalled=0;reg [68:0] stalled_command;
    reg last_busy_checked=0;
    kwt_dma dut(.*);
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>5000000) $fatal(1,"DMA test timeout");
        if(!rst_n) begin
            pending<=0;delay_left<=0;read_count<=0;write_count<=0;was_stalled<=0;
        end else begin
            if(was_stalled && (!m_valid || {m_read,m_addr,m_wdata,m_mask}!==stalled_command))
                $fatal(1,"DMA withdrew/changed a stalled command");
            was_stalled<=m_valid && !m_ready;
            stalled_command<={m_read,m_addr,m_wdata,m_mask};
            if(pending && delay_left>0) delay_left<=delay_left-1;
            if(m_rsp_valid && m_rsp_ready) pending<=0;
            if(m_valid && m_ready) begin
                if(m_addr<32'ha0010000 || m_addr>=32'ha0080000 || m_addr[1:0]!=0 || m_mask!=15)
                    $fatal(1,"Unsafe DMA address/mask %h",m_addr);
                pending<=1;pending_read<=m_read;
                delay_left<=fixed_delay!=0?fixed_delay:cycles%5;
                m_err<=0;
                if((inject_kind==1 && m_read) || (inject_kind==2 && !m_read) ||
                   (inject_kind==3 && !m_read && m_addr==32'ha003c5fc)) begin
                    m_err<=1;inject_kind<=0;
                end else if(m_read) m_rdata<=mem[m_addr[18:2]];
                else mem[m_addr[18:2]]<=m_wdata;
                if(m_read) read_count<=read_count+1;
                else begin
                    write_count<=write_count+1;
                    if(m_addr==32'ha003c5fc) delay_left<=40;
                end
            end
        end
    end
    task automatic bus(input bit read_,input [19:0] addr_,input [31:0] data_,input bit error_,output [31:0] value);
        begin
            @(negedge clk);cmd_valid=1;cmd_read=read_;cmd_addr=addr_;cmd_wdata=data_;rsp_ready=0;
            do @(posedge clk);while(!cmd_ready);
            @(negedge clk);cmd_valid=0;
            while(!rsp_valid) @(negedge clk);
            held=rsp_rdata;
            if(transactions%37==0) repeat(3) begin
                @(negedge clk);
                if(!rsp_valid || rsp_rdata!==held || rsp_err!==error_) $fatal(1,"Control response unstable");
            end
            value=rsp_rdata;
            if(rsp_err!==error_) $fatal(1,"Control error addr=%h expected=%b",addr_,error_);
            rsp_ready=1;@(negedge clk);rsp_ready=0;transactions=transactions+1;
        end
    endtask
    task automatic configure;
        begin
            bus(0,20'h20,32'ha0010000,0,rd);bus(0,20'h24,32'ha0018000,0,rd);
            bus(0,20'h28,32'ha0028000,0,rd);bus(0,20'h2c,32'ha0030000,0,rd);
            bus(0,20'h30,32'ha0062000,0,rd);bus(0,20'h34,32'ha006a000,0,rd);
            bus(0,20'h38,1,0,rd);bus(0,20'h3c,cfg[0],0,rd);
        end
    endtask
    task automatic wait_idle(input [4:0] expected_status);
        begin
            rd=1;polls=0;
            while(rd[0]) begin
                bus(1,4,0,0,rd);polls=polls+1;
                if(polls>500000) $fatal(1,"DMA did not finish/drain");
            end
            if(rd[4:0]!==expected_status) $fatal(1,"DMA status %h expected %h",rd,expected_status);
            if(m_valid || pending) $fatal(1,"Idle before outstanding transfers drained");
        end
    endtask
    initial begin
        $readmemh("output/vectors/task_00/x.hex",xv);$readmemh("output/vectors/task_00/w.hex",wv);
        $readmemh("output/vectors/task_00/b.hex",bv);$readmemh("output/ffn-vectors/task_00/expected.hex",expected);
        $readmemh("output/vectors/task_00/expected.hex",first_expected);
        $readmemh("output/ffn-vectors/task_00/w2_packed.hex",w2p);
        $readmemh("output/ffn-vectors/task_00/b2.hex",b2v);
        $readmemh("output/ffn-vectors/task_00/config.hex",cfg);
        for(j=0;j<3168;j=j+1) mem[16384+j]={xv[2*j+1][15:0],xv[2*j][15:0]};
        for(j=0;j<8192;j=j+1) mem[24576+j]={wv[2*j+1][15:0],wv[2*j][15:0]};
        for(j=0;j<256;j=j+1) mem[40960+j]=bv[j];
        for(j=0;j<8192;j=j+1) mem[100352+j]=w2p[j];
        for(j=0;j<64;j=j+1) mem[108544+j]=b2v[j];
        repeat(4) @(negedge clk);rst_n=1;
        configure();bus(1,20'h0c,0,0,rd);if(rd!==32'h4b575435) $fatal(1,"ID mismatch");
        bus(0,20'h20,32'ha0010002,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();bus(0,20'h2c,32'ha0010000,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();bus(0,20'h2c,32'ha0074000,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();bus(0,20'h20,32'ha007ce84,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();bus(0,20'h24,32'ha0078004,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();bus(0,20'h20,32'hfffffffc,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();bus(0,20'h30,32'ha0078004,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();bus(0,20'h34,32'ha0030000,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();bus(0,20'h38,2,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();bus(0,20'h3c,32'h00000020,0,rd);bus(0,0,1,1,rd);wait_idle(16);
        configure();if(read_count || write_count) $fatal(1,"Invalid configuration issued DMA traffic");
        cmd_wmask=1;bus(0,0,1,1,rd);cmd_wmask=15;

        // Abort while the first offered command has not been accepted.
        force_block=1;bus(0,0,1,0,rd);while(!m_valid) @(negedge clk);
        bus(0,0,2,0,rd);repeat(5) @(negedge clk);
        bus(1,4,0,0,rd);if(!rd[0]) $fatal(1,"Abort withdrew an offered command");
        force_block=0;wait_idle(8);

        // Last legal X/W packed ranges are accepted (one word beyond was rejected).
        force_block=1;bus(0,20'h20,32'ha007ce80,0,rd);bus(0,20'h24,32'ha0078000,0,rd);
        bus(0,0,1,0,rd);while(!m_valid) @(negedge clk);
        if(m_addr!==32'ha007ce80) $fatal(1,"Packed upper-bound address rejected");
        bus(0,0,2,0,rd);force_block=0;wait_idle(8);configure();

        // Abort with an accepted read and a delayed response; drain prefetched request too.
        fixed_delay=30;bus(0,0,1,0,rd);while(!pending) @(negedge clk);
        bus(0,0,2,0,rd);wait_idle(8);fixed_delay=0;

        // Read error, write error and write-side abort each recover without reset.
        inject_kind=1;bus(0,0,1,0,rd);wait_idle(4);
        inject_kind=2;bus(0,0,1,0,rd);wait_idle(4);
        inject_kind=3;bus(0,0,1,0,rd);wait_idle(4); // Final write failure must never report done.
        bus(0,0,1,0,rd);while(!(m_valid && !m_read)) @(negedge clk);
        force_block=1;bus(0,0,2,0,rd);repeat(5) @(negedge clk);force_block=0;wait_idle(8);

        // Reset cancels the bus response slot and all accelerator validity state.
        fixed_delay=30;bus(0,0,1,0,rd);while(!pending) @(negedge clk);
        rst_n=0;repeat(4) @(negedge clk);rst_n=1;fixed_delay=0;configure();
        bus(1,4,0,0,rd);if(rd!==0) $fatal(1,"Reset status mismatch");
        bus(0,0,1,0,rd);while(!(m_valid && !m_read)) @(negedge clk);
        fixed_delay=30;while(!(pending && !pending_read)) @(negedge clk);
        rst_n=0;repeat(4) @(negedge clk);rst_n=1;fixed_delay=0;configure();
        for(j=0;j<12672;j=j+1) mem[49152+j]=32'hdeadbeef;
        bus(0,0,1,0,rd);
        bus(0,20'h20,32'ha0010000,1,rd); // Busy configuration writes are rejected.
        bus(0,0,1,1,rd); // Busy start must not disturb the ongoing task.
        while(!(m_valid && !m_read)) @(negedge clk);
        force_block=1;repeat(1200) @(negedge clk);force_block=0;
        rd=1;polls=0;
        while(rd[0]) begin
            bus(1,4,0,0,rd);polls=polls+1;
            if(write_count==12672 && pending && delay_left>10) begin
                if(!rd[0] || rd[1]) $fatal(1,"Completion before final write acknowledgement");
                last_busy_checked=1;
            end
            if(polls>500000) $fatal(1,"Success run timeout");
        end
        if(rd[4:0]!==18 || !last_busy_checked) $fatal(1,"Success/status/final-response coverage failed %h",rd);
        for(j=0;j<6336;j=j+1)
            if({mem[49152+2*j+1],mem[49152+2*j]}!==expected[j]) $fatal(1,"DMA output mismatch %0d",j);
        for(j=0;j<15;j=j+1) begin
            bus(1,20'h40+20'(4*j),0,0,profile[j]);
            $display("FFN_PROFILE index=%0d value=%0d",j,profile[j]);
        end
        if(profile[0]!=profile[1]+profile[2]+profile[3] || profile[4]!=202752 ||
           profile[5]==0 || profile[9]!=19872 || profile[10]!=12672 ||
           profile[13]!=profile[0] || profile[12]>=profile[13]) $fatal(1,"Cycle accounting mismatch");
        bus(1,20'h7c,0,0,rd);if(rd!=101376) $fatal(1,"Second MAC counter");
        bus(1,20'h80,0,0,rd);if(rd!=25344) $fatal(1,"GELU counter");
        bus(1,20'h84,0,0,rd);if(rd!=0) $fatal(1,"GELU saturated");
        // Switch FFN -> independent first layer -> FFN without resetting chip.
        bus(0,20'h38,0,0,rd);bus(0,0,1,0,rd);wait_idle(2);
        for(j=0;j<25344;j=j+1)
            if({mem[49152+2*j+1],mem[49152+2*j]}!==first_expected[j]) $fatal(1,"First-layer mode switch mismatch %0d",j);
        bus(1,20'h7c,0,0,rd);if(rd!=0) $fatal(1,"Stale second MAC count");
        bus(1,20'h80,0,0,rd);if(rd!=0) $fatal(1,"Stale GELU count");
        configure();bus(0,0,1,0,rd);wait_idle(2);
        for(j=0;j<6336;j=j+1)
            if({mem[49152+2*j+1],mem[49152+2*j]}!==expected[j]) $fatal(1,"FFN mode recovery mismatch %0d",j);
        $display("FFN_PASS bit-exact outputs, delayed final write, burst loading, stalls, faults, abort, reset, counters");
        $finish;
    end
endmodule
