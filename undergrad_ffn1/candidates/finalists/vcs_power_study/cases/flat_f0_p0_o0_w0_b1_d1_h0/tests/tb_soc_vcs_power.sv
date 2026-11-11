`timescale 1ns/1fs
`include "size.vh"
`include "kwt_options.vh"
`include "kwt_optional.vh"
module tb_soc;
    string vcs_power_vcd_path;
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
    reg [31:0] xp[0:3167],wp[0:8191];
    // PACKED_DECL_END
    reg [63:0] expected[0:25343];
    reg [31:0] rd,lo,hi;
    reg [159:0] packed_result;reg [39:0] decoded_result;
    integer group_index,word_index,item_index;
    longint wfi_cycles=0,core_clock_edges=0;
    integer taskid,j,num_tasks=12,max_cycles=250000000;
    bit continuous=0;
    longint cycles=0,start_cycle,total_cycles=0,task_cycles;
    longint boot_cycle;
    bit measuring=0;
    integer shared_fetches=0,mail_reads=0,status_reads=0,itcm_pcs=0;
    integer host_load_accepts=0,host_load_responses=0,host_overlaps=0;
    string folder;
    kwt_ffn1_soc dut(.*);
    bit power_seen=0,power_started=0;
    always @(posedge h_valid) begin
        if(measuring && !power_started) begin
            if(h_read || h_addr!=32'ha0010000) $fatal(1,"Unexpected first Host load");
            power_started=1;
            $display("POWER_BEGIN task=%0d time_fs=%0.0f cycle=%0d",taskid,$realtime*1000000.0,cycles);
            $fflush();
        end
    end
    // Observe the last actual DMA write response, not later Host mailbox polling.
    always @(posedge clk) begin
        if(measuring && power_started && !power_seen && dut.bus.accelerator.retire &&
           dut.bus.accelerator.phase==4 && !dut.bus.accelerator.outstanding_read &&
           dut.bus.accelerator.write_received==`KWT_OUTPUT_WORDS-1 &&
           !dut.bus.accelerator.stopping) begin
            power_seen=1;
            $display("POWER_END task=%0d time_fs=%0.0f cycle=%0d",taskid,$realtime*1000000.0,cycles);
            $fflush();
        end
    end
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(measuring) begin
            if(dut.core_wfi) wfi_cycles<=wfi_cycles+1;
            if(inspect_pc[31:16]==16'h8000) itcm_pcs<=itcm_pcs+1;
            if(dut.c_valid && dut.c_ready && dut.c_read) begin
                if(dut.c_addr>=32'ha0000000 && dut.c_addr<32'ha000c000) shared_fetches<=shared_fetches+1;
                if(dut.c_addr==32'ha000f000) mail_reads<=mail_reads+1;
                if(dut.c_addr==32'h40000004) status_reads<=status_reads+1;
            end
        end
        if(cycles>max_cycles) $fatal(1,"SoC timeout pc=%h mail=%h",inspect_pc,rd);
    end
    always @(posedge dut.core_clk) if(measuring) core_clock_edges<=core_clock_edges+1;
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
        reg [159:0] group_bits;
        integer first_result;
        begin
            if(`KWT_PACKED40) begin
                first_result=(word_number/5)*4;
                group_bits={expected[first_result+3][39:0],expected[first_result+2][39:0],
                            expected[first_result+1][39:0],expected[first_result][39:0]};
                expected_output_word=group_bits[(word_number%5)*32+:32];
            end else if(word_number%2)
                expected_output_word=expected[word_number/2][63:32];
            else expected_output_word=expected[word_number/2][31:0];
        end
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
            if(!$value$plusargs("vcd_path=%s",vcs_power_vcd_path)) $fatal(1,"Missing vcd_path");
            $dumpfile(vcs_power_vcd_path);
            $dumpvars(0,tb_soc.dut);$dumpoff;
        end
        $readmemh("output/firmware/kwt.hex",fw);
        repeat(4) @(negedge clk);rst_n=1;
        for(j=0;j<`FW_WORDS;j=j+1) host(0,32'ha0000000+32'(4*j),fw[j],rd);
        for(taskid=0;taskid<num_tasks;taskid=taskid+1) begin
            folder=$sformatf("vectors/task_%02d",taskid);
            $readmemh({folder,"/x.hex"},xv);$readmemh({folder,"/w.hex"},wv);
            $readmemh({folder,"/b.hex"},bv);$readmemh({folder,"/expected.hex"},expected);
            // PACKED_CHECK_BEGIN
            $readmemh({folder,"/x_packed.hex"},xp);$readmemh({folder,"/w_packed.hex"},wp);
            for(j=0;j<3168;j=j+1)
                if(xp[j]!=={xv[2*j+1][15:0],xv[2*j][15:0]}) $fatal(1,"X packing mismatch %0d",j);
            for(j=0;j<8192;j=j+1)
                if(wp[j]!=={wv[2*j+1][15:0],wv[2*j][15:0]}) $fatal(1,"W packing mismatch %0d",j);
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
            shared_fetches=0;mail_reads=0;status_reads=0;itcm_pcs=0;wfi_cycles=0;core_clock_edges=0;measuring=1;
            start_cycle=cycles; power_seen=0; power_started=0;
            host_load_accepts=0;host_load_responses=0;host_overlaps=0;
            if($test$plusargs("vcd")) $dumpon;
            $display("MEASURE_BEGIN task=%0d time_ps=%0t cycle=%0d",taskid,$time,cycles);$fflush();
            // Real external loader transactions; included in measured task interval.
            if($test$plusargs("host_continuous")) begin
                host_load(32'ha0010000,3168,0);
                host_load(32'ha0018000,8192,1);
                host_load(32'ha0028000,256,2);
            end else begin
                for(j=0;j<3168;j=j+1) host(0,32'ha0010000+32'(4*j),xp[j],rd);
                for(j=0;j<8192;j=j+1) host(0,32'ha0018000+32'(4*j),wp[j],rd);
                for(j=0;j<256;j=j+1) host(0,32'ha0028000+32'(4*j),bv[j],rd);
            end
            $display("SOC_HOST task=%0d accepted=%0d retired=%0d overlaps=%0d",taskid,host_load_accepts,host_load_responses,host_overlaps);
            host(0,32'ha000f000,1,rd);
            if($test$plusargs("host_continuous") && (host_load_accepts!=11616 || host_load_responses!=11616 || host_overlaps==0))
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
            $display("SOC_BUS task=%0d shared_fetches=%0d mail_reads=%0d status_reads=%0d itcm_pcs=%0d",taskid,shared_fetches,mail_reads,status_reads,itcm_pcs);
            $display("SOC_ACTIVITY task=%0d wfi_cycles=%0d cpu_clock_edges=%0d",taskid,wfi_cycles,core_clock_edges);
            if(`KWT_IRQ && wfi_cycles==0) $fatal(1,"IRQ mode never entered WFI");
            if(`KWT_ITCM && (shared_fetches!=0 || itcm_pcs==0)) $fatal(1,"ITCM execution contract failed");
            if($test$plusargs("vcd")) $dumpoff;
            $display("MEASURE_END task=%0d time_ps=%0t cycle=%0d",taskid,$time,cycles);$fflush();
            host(1,32'ha000f004,0,rd);if(rd!=0) $fatal(1,"Driver returned error");
            if($test$plusargs("fast_checks")) bulk_check();
            else if(`KWT_PACKED40) begin
                for(group_index=0;group_index<6336;group_index=group_index+1) begin
                    for(word_index=0;word_index<5;word_index=word_index+1) begin
                        host(1,32'ha0030000+32'((group_index*5+word_index)*4),0,rd);
                        packed_result[32*word_index+:32]=rd;
                    end
                    for(item_index=0;item_index<4;item_index=item_index+1) begin
                        decoded_result=packed_result[40*item_index+:40];
                        if({{24{decoded_result[39]}},decoded_result}!==expected[group_index*4+item_index])
                            $fatal(1,"Packed SoC mismatch task=%0d index=%0d",taskid,group_index*4+item_index);
                    end
                end
            end else begin
            for(j=0;j<25344;j=j+1) begin
                host(1,32'ha0030000+32'(8*j),0,lo);host(1,32'ha0030004+32'(8*j),0,hi);
                if({hi,lo}!==expected[j]) $fatal(1,"SoC mismatch task=%0d index=%0d actual=%h expected=%h",taskid,j,{hi,lo},expected[j]);
            end
            end
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
                    if(j==9 && rd!=11616) $fatal(1,"DMA read count mismatch");
                    if(j==10 && rd!=`KWT_OUTPUT_WORDS) $fatal(1,"DMA write count mismatch");
                    $display("SOC_PROFILE task=%0d index=%0d value=%0d",taskid,j,rd);
                end
            end
            // PROFILE_END
            $display("SOC_TASK_PASS task=%0d cycles=%0d outputs=25344",taskid,task_cycles);
            $fflush();
        end
        $display("SOC_PASS tasks=%0d total_cycles=%0d nominal_tasks_per_second=%f",num_tasks,total_cycles,real'(num_tasks)*150000000.0/real'(total_cycles));
        $finish;
    end
endmodule
