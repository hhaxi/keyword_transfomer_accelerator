`timescale 1ns/1ps
`include "size.vh"
module tb_soc_ffn;
    reg clk=0;always #3.333 clk=~clk;
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
    reg [63:0] expected[0:6335];
    reg [31:0] w2p[0:8191],b2v[0:63],cfg[0:0];
    string ffnfolder;
    reg [31:0] rd,lo,hi;
    integer taskid,j,num_tasks=12,max_cycles=250000000;
    longint cycles=0,start_cycle,total_cycles=0,task_cycles;
    string folder;
    kwt_soc dut(.*);
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>max_cycles) $fatal(1,"SoC timeout pc=%h mail=%h",inspect_pc,rd);
    end
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
    initial begin
        if($value$plusargs("tasks=%d",num_tasks)) begin end
        if($value$plusargs("maxcycles=%d",max_cycles)) begin end
        if($test$plusargs("vcd")) begin
            if($test$plusargs("fst")) $dumpfile("output/design/soc.fst");
            else $dumpfile("output/design/soc.vcd");
            $dumpvars(0,tb_soc.dut);$dumpoff;
        end
        $readmemh("output/design/firmware/kwt.hex",fw);
        repeat(4) @(negedge clk);rst_n=1;
        for(j=0;j<`FW_WORDS;j=j+1) host(0,32'ha0000000+32'(4*j),fw[j],rd);
        for(taskid=0;taskid<num_tasks;taskid=taskid+1) begin
            folder=$sformatf("output/vectors/task_%02d",taskid);
            $readmemh({folder,"/x.hex"},xv);$readmemh({folder,"/w.hex"},wv);
            $readmemh({folder,"/b.hex"},bv);
            ffnfolder=$sformatf("output/ffn-vectors/task_%02d",taskid);
            $readmemh({ffnfolder,"/expected.hex"},expected);
            $readmemh({ffnfolder,"/w2_packed.hex"},w2p);$readmemh({ffnfolder,"/b2.hex"},b2v);
            $readmemh({ffnfolder,"/config.hex"},cfg);
            // PACKED_CHECK_BEGIN
            $readmemh({folder,"/x_packed.hex"},xp);$readmemh({folder,"/w_packed.hex"},wp);
            for(j=0;j<3168;j=j+1)
                if(xp[j]!=={xv[2*j+1][15:0],xv[2*j][15:0]}) $fatal(1,"X packing mismatch %0d",j);
            for(j=0;j<8192;j=j+1)
                if(wp[j]!=={wv[2*j+1][15:0],wv[2*j][15:0]}) $fatal(1,"W packing mismatch %0d",j);
            // PACKED_CHECK_END
            @(negedge clk);rst_n=0;boot_hold=1;repeat(5) @(negedge clk);rst_n=1;
            host(0,32'ha000f000,0,rd);host(0,32'ha000f004,0,rd);
            // All accelerator validity state is reset. Clear shared output before timing.
            for(j=0;j<12672;j=j+1) host(0,32'ha0030000+32'(4*j),0,rd);
            boot_hold=0;repeat(500) @(negedge clk);
            start_cycle=cycles;
            if($test$plusargs("vcd")) $dumpon;
            $display("MEASURE_BEGIN task=%0d time_ps=%0t cycle=%0d",taskid,$time,cycles);$fflush();
            // Real external loader transactions; included in measured task interval.
            for(j=0;j<3168;j=j+1) host(0,32'ha0010000+32'(4*j),xp[j],rd);
            for(j=0;j<8192;j=j+1) host(0,32'ha0018000+32'(4*j),wp[j],rd);
            for(j=0;j<256;j=j+1) host(0,32'ha0028000+32'(4*j),bv[j],rd);
            for(j=0;j<8192;j=j+1) host(0,32'ha0062000+32'(4*j),w2p[j],rd);
            for(j=0;j<64;j=j+1) host(0,32'ha006a000+32'(4*j),b2v[j],rd);
            host(0,32'ha000f008,cfg[0],rd);
            host(0,32'ha000f000,5,rd);
            $display("SOC_TASK_START task=%0d pc=%h cycle=%0d",taskid,inspect_pc,cycles);$fflush();
            rd=0;
            while(rd!=2) begin
                repeat(512) @(negedge clk);
                host(1,32'ha000f000,0,rd);
                if(rd==32'hdead || rd==32'hbad) $fatal(1,"Firmware failure %h pc=%h",rd,inspect_pc);
            end
            task_cycles=cycles-start_cycle;total_cycles+=task_cycles;
            if($test$plusargs("vcd")) $dumpoff;
            $display("MEASURE_END task=%0d time_ps=%0t cycle=%0d",taskid,$time,cycles);$fflush();
            host(1,32'ha000f004,0,rd);if(rd!=0) $fatal(1,"Driver returned error");
            for(j=0;j<6336;j=j+1) begin
                host(1,32'ha0030000+32'(8*j),0,lo);host(1,32'ha0030004+32'(8*j),0,hi);
                if({hi,lo}!==expected[j]) $fatal(1,"SoC mismatch task=%0d index=%0d actual=%h expected=%h",taskid,j,{hi,lo},expected[j]);
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
                    if(j==4 && rd!=202752) $fatal(1,"MAC cycle count mismatch");
                    if(j==9 && rd!=19872) $fatal(1,"DMA read count mismatch");
                    if(j==10 && rd!=12672) $fatal(1,"DMA write count mismatch");
                    $display("FFN_SOC_PROFILE task=%0d index=%0d value=%0d",taskid,j,rd);
                end
            end
            if($test$plusargs("profile")) begin
                for(j=0;j<3;j=j+1) begin
                    host(1,32'ha000f060+32'(4*j),0,rd);
                    if(j==0 && rd!=101376) $fatal(1,"Second MAC count mismatch");
                    if(j==1 && rd!=25344) $fatal(1,"GELU count mismatch");
                    if(j==2 && rd!=0) $fatal(1,"Unexpected GELU saturation");
                    $display("FFN_EXTRA task=%0d index=%0d value=%0d",taskid,j,rd);
                end
            end
            // OVERLAP_PROFILE_BEGIN
            if($test$plusargs("profile")) begin
                for(j=0;j<3;j=j+1) begin
                    host(1,32'ha000f06c+32'(4*j),0,rd);
                    if(j==0 && rd!=22085) $fatal(1,"GELU overlap mismatch");
                    if(j!=0 && rd==0) $fatal(1,"Load overlap/wait coverage missing");
                    $display("FFN_OVERLAP task=%0d index=%0d value=%0d",taskid,j,rd);
                end
            end
            // OVERLAP_PROFILE_END
            // PROFILE_END
            $display("FFN_SOC_TASK_PASS task=%0d cycles=%0d outputs=6336",taskid,task_cycles);
            $fflush();
        end
        $display("FFN_SOC_PASS tasks=%0d total_cycles=%0d nominal_tasks_per_second=%f",num_tasks,total_cycles,real'(num_tasks)*150000000.0/real'(total_cycles));
        $finish;
    end
endmodule
