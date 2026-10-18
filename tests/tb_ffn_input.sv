`timescale 1ns/1ps
// Real DMA/core, full-range FFN vectors; variable-latency two-credit memory.
module tb_ffn_input;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cmd_valid=0,cmd_read=0,rsp_ready=1;
    reg [19:0] cmd_addr=0;reg [31:0] cmd_wdata=0;wire [3:0] cmd_wmask=15;
    wire cmd_ready,rsp_valid,rsp_err;wire [31:0] rsp_rdata;
    wire m_valid,m_read,m_rsp_ready;wire [31:0] m_addr,m_wdata;wire [3:0] m_mask;
    wire result_valid,link_abort_out;wire [39:0] result_data;
    reg input_accepted=0;reg input_valid=0;wire input_ready;reg [31:0] input_data=0;
    integer sent=0,input_stalls=0,tile_wait=0,overlap_writes=0,weight_stalls=0;
    integer feed_period=1;reg feed=0,wait_for_input=0;
    reg input_held=0;reg [31:0] input_held_data;
    reg bus_held=0;reg [31:0] bus_addr;
    always @(negedge clk) begin
        if(input_accepted) input_valid=0;
        if(!feed || link_abort_in || link_abort_out) input_valid=0;
        else if(!input_valid && sent<3168 && cycle%feed_period==0) begin input_valid=1;input_data=x[sent];end
    end
    always @(posedge clk) if(rst_n) begin
        if(dut.core.xwrite && dut.core.read_operands && !dut.core.second_stage) $fatal(1,"Single-port X collision");
        if(dut.core.start && (!dut.core.second_ready || dut.core.nx<512)) $fatal(1,"Early weight/tile launch");
        if(dut.core.read_operands && !dut.core.second_stage && dut.core.nx<({6'd0,dut.core.operand_row}+13'd1)*64) $fatal(1,"Read before input resident");
        if(dut.core.state==10) tile_wait++;
        if(dut.core.xwrite && dut.core.second_stage) overlap_writes++;
        if(input_valid && !input_ready) begin input_stalls++;if(dut.read_received<16704) weight_stalls++;end
        input_accepted<=input_valid && input_ready;
        if(input_valid && input_ready) sent++;
        if(bus_held && (!m_valid || m_addr!==bus_addr)) $fatal(1,"Weight offer changed on stall/abort");
        bus_held<=m_valid && !m_ready;bus_addr<=m_addr;
        if(link_abort_in || link_abort_out || !feed) input_held<=0;
        else begin
            if(input_held && (!input_valid || input_data!==input_held_data)) $fatal(1,"Input offer unstable");
            input_held<=input_valid && !input_ready;input_held_data<=input_data;
        end
    end
    reg link_abort_in=0,block_result=0,block_response=0,inject_error=0;
    integer ideal=0,read_streak=0,max_read_streak=0,write_streak=0,max_write_streak=0;
    integer cycle=0,queued=0,due[0:1],max_pending=0,received=0,stalls=0;
    reg head=0,tail=0;reg [31:0] response[0:1];
    wire m_rsp_valid=queued!=0 && cycle>=due[head] && !block_response;
    wire m_ready=(queued<2 || m_rsp_valid) && (ideal!=0 || cycle%7!=0);
    wire [31:0] m_rdata=response[head];wire m_err=inject_error;
    wire result_ready=(!wait_for_input || sent==3168) && !block_result && cycle%13>4;
    reg [31:0] memory[0:131071],x[0:3167],w[0:8191],b[0:255],w2[0:8191],b2[0:63];
    reg [63:0] expected[0:6335];
    reg held=0;reg [39:0] held_data;
    reg [31:0] rd;
    reg [159:0] packed_group;
    reg [39:0] unpacked;
    integer mode_,case_,j,k,polls;string folder;
    kwt_dma #(.STREAM_ENABLE(1)) dut(.preload_permit(1'b1),.*);
    always @(posedge clk) begin
        cycle<=cycle+1;
        if(cycle>8000000) $fatal(1,"Transport timeout");
        if(!rst_n) begin queued<=0;head<=0;tail<=0;held<=0;end
        else begin
            case({m_valid && m_ready,m_rsp_valid})
                2'b10:queued<=queued+1;
                2'b01:queued<=queued-1;
                default:begin end
            endcase
            if(m_valid && m_ready && m_read) read_streak<=read_streak+1;else read_streak<=0;
            if(m_valid && m_ready && !m_read) write_streak<=write_streak+1;else write_streak<=0;
            if(read_streak>max_read_streak) max_read_streak<=read_streak;
            if(write_streak>max_write_streak) max_write_streak<=write_streak;
            if(queued>max_pending) max_pending<=queued;
            if(m_valid && m_ready) begin
                if(m_mask!=15 || m_addr<32'ha0010000 || m_addr>=32'ha0080000) $fatal(1,"DMA range");
                due[tail]<=cycle+(ideal!=0 ? 1 : 3+cycle%5);response[tail]<=memory[m_addr[18:2]];tail<=!tail;
                if(!m_read) memory[m_addr[18:2]]<=m_wdata;
            end
            if(m_rsp_valid) head<=!head;
            if(link_abort_in || link_abort_out) held<=0;
            else begin
                if(held && (!result_valid || result_data!==held_data)) $fatal(1,"Stream changed under backpressure");
                held<=result_valid && !result_ready;held_data<=result_data;
                if(result_valid && !result_ready) stalls++;
                if(result_valid && result_ready) begin
                    if(received>=6336 || {{24{result_data[39]}},result_data}!==expected[received]) $fatal(1,"Stream data/order");
                    received++;
                end
            end
        end
    end
    task automatic regbus(input bit read_,input [19:0] addr,input [31:0] value);
        begin
            @(negedge clk);cmd_valid=1;cmd_read=read_;cmd_addr=addr;cmd_wdata=value;
            do @(posedge clk);while(!cmd_ready);
            @(negedge clk);cmd_valid=0;
            while(!rsp_valid) @(negedge clk);
            if(rsp_err) $fatal(1,"Control error %h",addr);
            rd=rsp_rdata;@(negedge clk);
        end
    endtask
    task automatic wait_done;
        begin
            rd=1;polls=0;
            while(rd[0]) begin regbus(1,4,0);polls++;if(polls>200000) $fatal(1,"Completion timeout");end
            if(rd!=2 || queued || m_valid) $fatal(1,"Completion/status/drain %h",rd);
        end
    endtask
    initial begin
        if($value$plusargs("ideal=%d",ideal)) begin end
        repeat(4) @(negedge clk);rst_n=1;
        regbus(0,20'h20,32'ha0010000);regbus(0,20'h24,32'ha0020000);regbus(0,20'h28,32'ha0028000);
        regbus(0,20'h2c,32'ha0030000);regbus(0,20'h30,32'ha0040000);regbus(0,20'h34,32'ha0048000);regbus(0,20'h3c,0);
        regbus(0,20'h38,4);
        // Two accepted reads must both retire after abort or response error.
        block_response=1;regbus(0,0,1);while(queued!=2) @(negedge clk);
        regbus(0,0,2);block_response=0;@(negedge clk);block_response=1;
        if(queued!=1 || !dut.active) $fatal(1,"Two-credit abort ended early");
        block_response=0;rd=1;while(rd[0]) regbus(1,4,0);
        if(rd!=8 || queued || m_valid) $fatal(1,"Two-credit abort drain");
        block_response=1;regbus(0,0,1);while(queued!=2) @(negedge clk);
        repeat(12) @(negedge clk);
        inject_error=1;block_response=0;@(negedge clk);block_response=1;inject_error=0;
        if(queued!=1 || !dut.active) $fatal(1,"Two-credit fault ended early");
        block_response=0;rd=1;while(rd[0]) regbus(1,4,0);
        if(rd!=4 || queued || m_valid) $fatal(1,"Two-credit fault drain");
        for(case_=0;case_<3;case_++) begin
            folder=$sformatf("output/ffn-edges/case_%0d/",case_);
            $readmemh({folder,"x.hex"},x);$readmemh({folder,"w.hex"},w);$readmemh({folder,"b.hex"},b);
            $readmemh({folder,"w2.hex"},w2);$readmemh({folder,"b2.hex"},b2);$readmemh({folder,"expected.hex"},expected);
            for(j=0;j<3168;j++) memory[16384+j]=x[j];
            for(j=0;j<8192;j++) begin memory[32768+j]=w[j];memory[65536+j]=w2[j];end
            for(j=0;j<256;j++) memory[40960+j]=b[j];
            for(j=0;j<64;j++) memory[73728+j]=b2[j];
            for(mode_=4;mode_<=4;mode_++) begin
                received=0;sent=0;feed_period=case_==1 ? 100 : 1;wait_for_input=case_!=1;feed=1;regbus(0,20'h38,32'(mode_));regbus(0,0,1);wait_done();feed=0;
                if(sent!=3168 || dut.input_words!=3168) $fatal(1,"Input count");
                if(mode_==2) begin
                    for(j=0;j<1584;j++) begin
                        for(k=0;k<5;k++) packed_group[k*32+:32]=memory[49152+j*5+k];
                        for(k=0;k<4;k++) begin
                            unpacked=packed_group[k*40+:40];
                            if({{24{unpacked[39]}},unpacked}!==expected[j*4+k]) $fatal(1,"Packed40 mismatch");
                        end
                    end
                end else if(received!=6336) $fatal(1,"Stream length");
                regbus(1,20'h68,0);if(rd!=(mode_==2 ? 7920 : 0)) $fatal(1,"Write count");
                regbus(1,20'h64,0);if(rd!=16704) $fatal(1,"Read count");
                $display("FFN_INPUT_CASE_PASS case=%0d mode=%0d",case_,mode_);
            end
        end
        // A stalled consumer can cancel, drain requests, then restart cleanly.
        received=0;sent=0;feed=1;feed_period=1;wait_for_input=0;block_result=1;regbus(0,0,1);
        while(!result_valid) @(negedge clk);
        repeat(20) @(negedge clk);feed=0;link_abort_in=1;
        repeat(5) @(negedge clk);link_abort_in=0;
        rd=1;while(rd[0]) regbus(1,4,0);
        if(rd!=4 || queued || m_valid || result_valid) $fatal(1,"Stream cancellation");
        // Cancel while weights, a partial first tile, and a later tile are pending.
        for(k=0;k<3;k++) begin
            received=0;sent=0;feed=1;feed_period=20;block_result=1;
            regbus(0,0,1);
            if(k==0) begin while(dut.read_received<100) @(negedge clk);end
            else begin while(sent<(k==1 ? 255 : 600)) @(negedge clk);end
            feed=0;regbus(0,0,2);rd=1;while(rd[0]) regbus(1,4,0);
            if(rd!=8 || queued || m_valid || dut.core.nx!=0) $fatal(1,"Partial-input abort drain/reset");
        end
        block_result=0;received=0;sent=0;feed=1;feed_period=1;regbus(0,0,1);wait_done();feed=0;
        if(!input_stalls || !tile_wait || !overlap_writes || !weight_stalls) $fatal(1,"Input coverage");
        $display("INPUT_COVERAGE stalls=%0d tile_wait=%0d overlap_writes=%0d weight_stalls=%0d",input_stalls,tile_wait,overlap_writes,weight_stalls);
        if(received!=6336 || max_pending!=2 || !stalls) $fatal(1,"Coverage/restart");
        if(ideal!=0 && (max_read_streak<16704)) $fatal(1,"Continuous transfer coverage");
        $display("FFN_INPUT_BURST ideal=%0d read_streak=%0d write_streak=%0d",ideal,max_read_streak,max_write_streak);
        $display("FFN_INPUT_PASS packed40 stream40 full_range two_outstanding abort_drain error_drain cancellation restart stalls=%0d",stalls);
        $finish;
    end
endmodule
