`timescale 1ns/1fs
`include "size.vh"
`include "kwt_options.vh"
`include "kwt_optional.vh"
module tb_soc;
    kwt_measure_fs measurement_clock();
    reg clk=0;always begin #3.333333 clk=1; #3.333334 clk=0; end
    reg rst_n=0,boot_hold=1;
    reg h_valid=0,h_read=0,h_rsp_ready=0;
    reg [31:0] h_addr=0,h_wdata=0;
    reg [3:0] h_mask=15;
    wire h_ready,h_rsp_valid,h_err;
    wire [31:0] h_rdata,inspect_pc;
    reg [31:0] fw[0:`FW_WORDS-1];
    reg [31:0] xv[0:6335],wv[0:16383],bv[0:255];
    // PACKED_DECL_BEGIN
    reg [31:0] xp[0:3355],wp[0:8223];
    reg [511:0] x_header;
    // PACKED_DECL_END
    reg [63:0] expected_raw[0:25343];
    reg [31:0] expected_q16[0:`KWT_OUTPUT_WORDS-1];
    reg [31:0] rd;
    integer raw_checked=0;
    integer weight_words, expected_weight_words,x_words,expected_x_words;
    reg [31:0] compressed_count[0:0],x_compressed_count[0:0];
    longint wfi_cycles=0,core_clock_edges=0,ifu_clock_edges=0,exu_clock_edges=0;
    integer taskid,j,num_tasks=12,max_cycles=250000000;
    bit continuous=0;
    longint cycles=0,start_cycle,total_cycles=0,task_cycles;
    longint boot_cycle;
    bit measuring=0;
    integer shared_fetches=0,mail_reads=0,status_reads=0,itcm_pcs=0;
    integer host_load_accepts=0,host_load_responses=0,host_overlaps=0;
    string folder;
    string dump_path;
    kwt_ffn1_soc dut(.*);
    bit power_seen=0,power_started=0,activity_closed=0;
    wire activity_window=power_started && !activity_closed;
    `include "cg_monitor.svh"
    `include "cycle_breakdown.svh"
    `include "single_port_monitor.svh"
`ifdef KWT_COVERAGE
    `include "verification_coverage.svh"
`endif
`ifdef KWT_GATE_LEVEL_POWER
    // Probe the DMA interface, whose port names survive hierarchy-preserving DC.
    integer dma_responses=0;
    always @(posedge clk)
        if (measuring && dut.bus.accelerator.m_rsp_valid && dut.bus.accelerator.m_rsp_ready)
            dma_responses <= dma_responses + 1;
`else
    always @(posedge clk) begin
        if (measuring && dut.bus.accelerator.tile_engine.core.push) begin
            for (int r=0; r<int'(dut.bus.accelerator.tile_engine.core.valid_rows); r++) begin
                for (int c=0; c<`KWT_TILE_COLS; c++) begin
                    int idx;
                    idx=(int'(dut.bus.accelerator.tile_engine.core.row)+r)*256+
                        int'(dut.bus.accelerator.tile_engine.core.col)+c;
                    if (dut.bus.accelerator.tile_engine.core.group_values[(r*`KWT_TILE_COLS+c)*40+:40]
                        !==expected_raw[idx][39:0])
                        $fatal(1,"INT40 mismatch task=%0d index=%0d",taskid,idx);
                end
            end
            raw_checked=raw_checked+`KWT_TILE_COLS*int'(dut.bus.accelerator.tile_engine.core.valid_rows);
        end
    end
`endif
    always @(posedge h_valid) begin
        if(measuring && !power_started) begin
            if(h_read || h_addr!=32'ha0010000) $fatal(1,"Unexpected first Host load");
            power_started=1; cg_begin();
            $display("POWER_BEGIN task=%0d time_fs=%0d cycle=%0d",taskid,measurement_clock.now_fs(),cycles);
            $fflush();
        end
    end
    // Observe the last actual DMA write response, not later Host mailbox polling.
    always @(posedge clk) begin
        if(!measuring) activity_closed<=0;
        if(measuring && power_started && !power_seen &&
`ifdef KWT_GATE_LEVEL_POWER
           dut.bus.accelerator.m_rsp_valid && dut.bus.accelerator.m_rsp_ready &&
           dma_responses==weight_words+x_words+256+`KWT_OUTPUT_WORDS-1
`else
           dut.bus.accelerator.retire &&
           dut.bus.accelerator.phase==4 && !dut.bus.accelerator.outstanding_read &&
           dut.bus.accelerator.write_received==`KWT_OUTPUT_WORDS-1 &&
           !dut.bus.accelerator.stopping
`endif
           ) begin
            power_seen=1;activity_closed<=1;
            $display("POWER_END task=%0d time_fs=%0d cycle=%0d",taskid,measurement_clock.now_fs(),cycles);
            cg_end();
            $fflush();
        end
    end
    always @(posedge clk) begin
        cycles<=cycles+1;
`ifndef KWT_GATE_LEVEL_POWER
        if(measuring && activity_window) begin
            if(dut.core_wfi) wfi_cycles<=wfi_cycles+1;
            if(inspect_pc[31:16]==16'h8000) itcm_pcs<=itcm_pcs+1;
            if(dut.c_valid && dut.c_ready && dut.c_read) begin
                if(dut.c_addr>=32'ha0000000 && dut.c_addr<32'ha000c000) shared_fetches<=shared_fetches+1;
                if(dut.c_addr==32'ha000f000) mail_reads<=mail_reads+1;
                if(dut.c_addr==32'h40000004) status_reads<=status_reads+1;
            end
        end
`endif
        if(cycles>max_cycles) $fatal(1,"SoC timeout pc=%h mail=%h",inspect_pc,rd);
    end
`ifndef KWT_GATE_LEVEL_POWER
    always @(posedge dut.core_clk) if(measuring && activity_window) core_clock_edges<=core_clock_edges+1;
    always @(posedge dut.cpu.u_e203_cpu.clk_core_ifu) if(measuring && activity_window) ifu_clock_edges<=ifu_clock_edges+1;
    always @(posedge dut.cpu.u_e203_cpu.clk_core_exu) if(measuring && activity_window) exu_clock_edges<=exu_clock_edges+1;
`endif
    task automatic host(input bit read_,input [31:0] addr_,input [31:0] data_,output [31:0] result);
        begin
            @(negedge clk);h_valid=1;h_read=read_;h_addr=addr_;h_wdata=data_;h_rsp_ready=0;
            do @(posedge clk);while(!h_ready);
            @(negedge clk);h_valid=0;
            while(!h_rsp_valid) @(negedge clk);
            if(h_err) $fatal(1,"Host bus error %h",addr_);
            result=h_rdata;h_rsp_ready=1;
            @(negedge clk);h_rsp_ready=0;
        end
    endtask
    // Keep one request offer stable until accepted; retire responses independently.
    // The fabric may retire the preceding response and accept this offer together.
    task automatic host_load(input [31:0] base,input integer words,input integer kind);
        integer issued,retired;
        begin
            issued=0;retired=0;
            @(negedge clk);h_rsp_ready=1;
            while(retired<words) begin
                h_valid=issued<words;h_read=0;h_mask=15;
                h_addr=base+32'(issued*4);
                if(issued<words) begin
                    case(kind)
                        0:h_wdata=xp[issued];
                        1:h_wdata=wp[issued];
                        default:h_wdata=bv[issued];
                    endcase
                end
                @(posedge clk);
                if(h_valid && h_ready && h_rsp_valid && h_rsp_ready) host_overlaps=host_overlaps+1;
                if(h_valid && h_ready) begin issued=issued+1;host_load_accepts=host_load_accepts+1;end
                if(h_rsp_valid && h_rsp_ready) begin
                    if(h_err) $fatal(1,"Continuous Host error");
                    retired=retired+1;host_load_responses=host_load_responses+1;
                end
                if(retired>issued) $fatal(1,"Unexpected Host response");
                @(negedge clk);
            end
            h_valid=0;h_rsp_ready=0;
            if(issued!=words) $fatal(1,"Incomplete Host load");
        end
    endtask
    // Used only outside MEASURE_BEGIN..END. All words still cross the legal
    // Host interface; acceptance and response accounting are independent.
    function automatic [31:0] expected_output_word(input integer word_number);
        expected_output_word=expected_q16[word_number];
    endfunction
    task automatic bulk_output(input bit check_result);
        integer issued,retired,overlaps;
        reg [31:0] golden_word;
        begin
            if(measuring) $fatal(1,"Bulk output traffic entered measured interval");
            issued=0;retired=0;overlaps=0;
            @(negedge clk);h_rsp_ready=1;
            while(retired<`KWT_OUTPUT_WORDS) begin
                h_valid=issued<`KWT_OUTPUT_WORDS;h_read=check_result;h_mask=15;
                h_addr=32'ha0030000+32'(issued*4);h_wdata=0;
                @(posedge clk);
                if(h_valid && h_ready && h_rsp_valid && h_rsp_ready) overlaps=overlaps+1;
                if(h_rsp_valid && h_rsp_ready) begin
                    if(h_err) $fatal(1,"Bulk Host output response error word=%0d read=%0d",retired,check_result);
                    if(retired>=issued) $fatal(1,"Unexpected bulk Host response word=%0d issued=%0d",retired,issued);
                    if(check_result) begin
                        golden_word=expected_output_word(retired);
                        if(h_rdata!==golden_word)
                            $fatal(1,"Bulk SoC mismatch task=%0d word=%0d actual=%h expected=%h",taskid,retired,h_rdata,golden_word);
                    end
                    retired=retired+1;
                end
                if(h_valid && h_ready) issued=issued+1;
                @(negedge clk);
            end
            h_valid=0;h_rsp_ready=0;
            if(issued!=`KWT_OUTPUT_WORDS || retired!=issued || overlaps==0)
                $fatal(1,"Incomplete bulk Host output issued=%0d retired=%0d overlaps=%0d",issued,retired,overlaps);
            $display("SOC_FAST_CHECK task=%0d read=%0d accepted=%0d retired=%0d overlaps=%0d",taskid,check_result,issued,retired,overlaps);
        end
    endtask
    task automatic bulk_clear;
        begin bulk_output(0); end
    endtask
    task automatic bulk_check;
        begin bulk_output(1); end
    endtask
    initial begin
        if($value$plusargs("tasks=%d",num_tasks)) begin end
        continuous=$test$plusargs("continuous");
        if($value$plusargs("maxcycles=%d",max_cycles)) begin end
        if($test$plusargs("vcd")) begin
            if($value$plusargs("vcd_path=%s",dump_path)) $dumpfile(dump_path);
            else if($test$plusargs("fst")) $dumpfile("output/soc.fst");
            else $dumpfile("output/soc.vcd");
            $dumpvars(0,tb_soc.dut);$dumpoff;
        end
        $readmemh("output/firmware/kwt.hex",fw);
        repeat(4) @(negedge clk);rst_n=1;
        for(j=0;j<`FW_WORDS;j=j+1) host(0,32'ha0000000+32'(4*j),fw[j],rd);
        for(taskid=0;taskid<num_tasks;taskid=taskid+1) begin
            folder=$sformatf("vectors/task_%02d",taskid);
            $readmemh({folder,"/x.hex"},xv);$readmemh({folder,"/w.hex"},wv);
            $readmemh({folder,"/b.hex"},bv);$readmemh({folder,"/expected.hex"},expected_raw);
            $readmemh($sformatf("output/expected_q16/task_%02d.hex",taskid),expected_q16);
            // PACKED_CHECK_BEGIN
            if(`KWT_X_DELTA) begin
                $readmemh({folder,"/x_compressed_words.hex"},x_compressed_count);
                x_words=int'(x_compressed_count[0]);
                if(x_words<214 || x_words>3356)$fatal(1,"Bad X word count");
                $readmemh({folder,"/x_compressed.hex"},xp,0,x_words-1);
                for(j=0;j<16;j=j+1)x_header[j*32+:32]=xp[j];
                if(x_header[511:496]!=16'h5844 || x_header[495]!=1'(`KWT_TAIL_FIRST))$fatal(1,"X header signature/order mismatch");
                expected_x_words=16;
                for(j=0;j<99;j=j+1)expected_x_words+=2*(1+int'(x_header[j*5+:5]));
                if(expected_x_words!=x_words)$fatal(1,"X metadata length mismatch");
            end else begin
                x_words=3168;$readmemh({folder,"/x_packed.hex"},xp,0,3167);
            end
            $readmemh({folder,"/w_compressed_words.hex"},compressed_count);
            weight_words=int'(compressed_count[0]);
            if(weight_words<544 || weight_words>8224) $fatal(1,"Bad compressed word count");
            $readmemh({folder,"/w_compressed.hex"},wp,0,weight_words-1);
            if(!`KWT_X_DELTA) for(j=0;j<3168;j=j+1)
                if(xp[j]!=={xv[2*j+1][15:0],xv[2*j][15:0]}) $fatal(1,"X packing mismatch %0d",j);
            expected_weight_words=32;
            for(j=0;j<256;j=j+1) expected_weight_words+=2*(1+int'(wp[j/8][(j%8)*4+:4]));
            if(expected_weight_words!=weight_words) $fatal(1,"Compressed metadata length mismatch");
            // PACKED_CHECK_END
            if(!continuous || taskid==0) begin
                @(negedge clk);rst_n=0;boot_hold=1;repeat(5) @(negedge clk);rst_n=1;
            end
            host(0,32'ha000f000,0,rd);host(0,32'ha000f004,0,rd);
            if(`KWT_ITCM && (!continuous || taskid==0)) host(0,32'ha000f008,0,rd);
            // All accelerator validity state is reset. Clear shared output before timing.
            if($test$plusargs("fast_checks")) bulk_clear();
            else for(j=0;j<`KWT_OUTPUT_WORDS;j=j+1) host(0,32'ha0030000+32'(4*j),0,rd);
            boot_cycle=cycles;boot_hold=0;
            if(`KWT_ITCM && (!continuous || taskid==0)) begin
                rd=0;
                while(rd!=32'h4954434d) host(1,32'ha000f008,0,rd);
            end
            repeat(500) @(negedge clk);
            $display("SOC_BOOT task=%0d cycles=%0d",taskid,cycles-boot_cycle);
            shared_fetches=0;mail_reads=0;status_reads=0;itcm_pcs=0;wfi_cycles=0;core_clock_edges=0;ifu_clock_edges=0;exu_clock_edges=0;measuring=1;
            start_cycle=cycles; power_seen=0; power_started=0; raw_checked=0;
`ifdef KWT_GATE_LEVEL_POWER
            dma_responses=0;
`endif
            host_load_accepts=0;host_load_responses=0;host_overlaps=0;
            if($test$plusargs("vcd")) $dumpon;
            $display("MEASURE_BEGIN task=%0d time_ps=%0t cycle=%0d",taskid,$time,cycles);$fflush();
            // Real external loader transactions; included in measured task interval.
            if($test$plusargs("host_continuous")) begin
                host_load(32'ha0010000,x_words,0);
                host_load(32'ha0018000,weight_words,1);
                host_load(32'ha0028000,256,2);
            end else begin
                for(j=0;j<x_words;j=j+1) host(0,32'ha0010000+32'(4*j),xp[j],rd);
                for(j=0;j<weight_words;j=j+1) host(0,32'ha0018000+32'(4*j),wp[j],rd);
                for(j=0;j<256;j=j+1) host(0,32'ha0028000+32'(4*j),bv[j],rd);
            end
            if($test$plusargs("cycle_breakdown")) $display("CYCLE_EVENT task=%0d event=host_done cycle=%0d",taskid,cycles);
            $display("SOC_HOST task=%0d accepted=%0d retired=%0d overlaps=%0d",taskid,host_load_accepts,host_load_responses,host_overlaps);
            host(0,32'ha000f000,1,rd);
            if($test$plusargs("host_continuous") && (host_load_accepts!=weight_words+x_words+256 || host_load_responses!=weight_words+x_words+256 || host_overlaps==0))
                $fatal(1,"Continuous Host contract missing: accepted/retired/overlap counts");
            $display("SOC_TASK_START task=%0d pc=%h cycle=%0d",taskid,inspect_pc,cycles);$fflush();
            rd=0;
            while(rd!=2) begin
                repeat(512) @(negedge clk);
                host(1,32'ha000f000,0,rd);
                if(rd==32'hdead || rd==32'hbad) $fatal(1,"Firmware failure %h pc=%h",rd,inspect_pc);
            end
            if(!power_seen) $fatal(1,"Final DMA write-response boundary missing");
            task_cycles=cycles-start_cycle;total_cycles+=task_cycles;
            measuring=0;
`ifndef KWT_GATE_LEVEL_POWER
            $display("SOC_BUS task=%0d shared_fetches=%0d mail_reads=%0d status_reads=%0d itcm_pcs=%0d",taskid,shared_fetches,mail_reads,status_reads,itcm_pcs);
            $display("SOC_ACTIVITY task=%0d wfi_cycles=%0d cpu_clock_edges=%0d ifu_clock_edges=%0d exu_clock_edges=%0d",
                     taskid,wfi_cycles,core_clock_edges,ifu_clock_edges,exu_clock_edges);
            if(`KWT_IRQ && wfi_cycles==0) $fatal(1,"IRQ mode never entered WFI");
            if(`KWT_ITCM && (shared_fetches!=0 || itcm_pcs==0)) $fatal(1,"ITCM execution contract failed");
`endif
            if($test$plusargs("vcd")) $dumpoff;
            $display("MEASURE_END task=%0d time_ps=%0t cycle=%0d",taskid,$time,cycles);$fflush();
            host(1,32'ha000f004,0,rd);if(rd!=0) $fatal(1,"Driver returned error");
            if($test$plusargs("fast_checks")) bulk_check();
            else for(j=0;j<`KWT_OUTPUT_WORDS;j=j+1) begin
                host(1,32'ha0030000+32'(4*j),0,rd);
                if(rd!==expected_output_word(j))
                    $fatal(1,"INT16 word mismatch task=%0d word=%0d",taskid,j);
            end
`ifndef KWT_GATE_LEVEL_POWER
            if (raw_checked!=25344) $fatal(1,"INT40 checked count mismatch");
`endif
            // PROFILE_BEGIN: optional reads after the measured interval and result verification.
            if($test$plusargs("profile")) begin
                host(0,32'ha000f000,3,rd);
                rd=0;j=0;
                while(rd!=4) begin
                    host(1,32'ha000f000,0,rd);j=j+1;
                    if(j>10000) $fatal(1,"Profile request timeout");
                end
                host(1,32'ha000f05c,0,rd);
                if(rd!==32'h50524633) $fatal(1,"Profile publication missing");
                for(j=0;j<15;j=j+1) begin
                    host(1,32'ha000f020+32'(4*j),0,rd);
                    if(j==4 && rd!=`KWT_EXPECTED_MAC_CYCLES) $fatal(1,"MAC cycle count mismatch");
                    if(j==9 && rd!=32'(weight_words+x_words+256)) $fatal(1,"DMA read count mismatch");
                    if(j==10 && rd!=`KWT_OUTPUT_WORDS) $fatal(1,"DMA write count mismatch");
                    $display("SOC_PROFILE task=%0d index=%0d value=%0d",taskid,j,rd);
                end
            end
            // PROFILE_END
            $display("SOC_TASK_PASS task=%0d cycles=%0d outputs=25344",taskid,task_cycles);
            $fflush();
        end
`ifdef KWT_COVERAGE
        coverage_protocol();
        coverage_report();
`endif
        $display("SOC_PASS tasks=%0d total_cycles=%0d nominal_tasks_per_second=%f",num_tasks,total_cycles,real'(num_tasks)*150000000.0/real'(total_cycles));
        $finish;
    end
endmodule

module kwt_measure_fs;
 timeunit 1fs;
 timeprecision 1fs;
 function automatic time now_fs();
  now_fs=$time;
 endfunction
endmodule
