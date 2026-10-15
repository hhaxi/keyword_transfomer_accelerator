`timescale 1ns/1ps
`include "encoder_size.vh"
module tb_encoder_soc;
    reg clk=0;always #3.333 clk=~clk;
    reg rst_n=0,boot_hold=1,h_valid=0,h_read=0,h_rsp_ready=0;
    reg [31:0] h_addr=0,h_wdata=0;reg [3:0] h_mask=15;
    wire h_ready,h_rsp_valid,h_err;wire [31:0] h_rdata,inspect_pc;
    reg [31:0] fw[0:`ENC_FW_WORDS-1],input_x[0:6335],expected[0:6335];
    reg [31:0] params[0:16703],w1[0:8191],w2[0:8191],b1[0:255],b2[0:63],cfg[0:1];
    reg [31:0] rd,configuration;
    integer taskid,li,j,n,num_tasks=12,first_task=0,baseline=0;
    longint cycles=0,start_cycle,task_cycles,total_cycles=0;
    string folder;
    kwt_encoder_soc dut(.*);
`ifdef ENCODER_MEMORY_METRICS
    reg measure=0;
    `include "encoder_memory_monitor.svh"
`endif
`ifdef ENCODER_PHASE_METRICS
    reg encoder_was_busy=0;
    longint phase_total;
    always @(negedge clk) begin
        if(!rst_n) encoder_was_busy=0;
        else begin
            if(encoder_was_busy && !dut.bus.encoder.busy) begin
                phase_total=0;
                for(integer c=0;c<10;c++) begin
                    phase_total+=64'(dut.bus.encoder.phase_cycles[c]);
                    $display("ENC_PHASE task=%0d layer=%0d op=%0d index=%0d value=%0d",taskid,li,dut.bus.encoder.operation,c,dut.bus.encoder.phase_cycles[c]);
                end
                if(phase_total!=64'(dut.bus.encoder.cycles)) $fatal(1,"Phase cycle accounting");
                $display("ENC_DMA_WAIT task=%0d layer=%0d op=%0d request=%0d response=%0d refill=%0d",taskid,li,dut.bus.encoder.operation,dut.bus.encoder.dma_request_wait,dut.bus.encoder.dma_response_wait,dut.bus.encoder.dma_retire_refill);
            end
            encoder_was_busy=dut.bus.encoder.busy;
        end
    end
`endif
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>600000000) $fatal(1,"Encoder SoC timeout pc=%h",inspect_pc);
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
        if($value$plusargs("first=%d",first_task)) begin end
        if($value$plusargs("baseline=%d",baseline)) begin end
        if(first_task<0 || num_tasks<1 || first_task+num_tasks>12) $fatal(1,"Invalid task range");
        if($test$plusargs("activity")) begin $dumpfile("output/encoder-design/encoder-soc.fst");$dumpvars(0,dut);$dumpoff;end
        $readmemh("output/encoder-design/firmware/encoder.hex",fw);
        repeat(4) @(negedge clk);rst_n=1;
        for(j=0;j<`ENC_FW_WORDS;j++) host(0,32'ha0000000+32'(4*j),fw[j],rd);
        for(taskid=first_task;taskid<first_task+num_tasks;taskid++) begin
            folder=$sformatf("output/encoder-vectors/task_%02d",taskid);
            $readmemh({folder,"/input.hex"},input_x);$readmemh({folder,"/expected.hex"},expected);
            @(negedge clk);rst_n=0;boot_hold=1;repeat(5) @(negedge clk);rst_n=1;
            host(0,32'ha000f000,0,rd);host(0,32'ha000f004,0,rd);
            for(j=0;j<6336;j++) host(0,32'ha0064000+32'(4*j),32'hdeadbeef,rd);
            boot_hold=0;repeat(500) @(negedge clk);start_cycle=cycles;
`ifdef ENCODER_MEMORY_METRICS
            measure=1;
`endif
            if($test$plusargs("activity")) $dumpon;
            $display("ENC_MEASURE_BEGIN task=%0d cycle=%0d baseline=%0d",taskid,cycles,baseline);$fflush();
            for(j=0;j<6336;j++) host(0,32'ha0010000+32'(4*j),input_x[j],rd);
            for(li=0;li<12;li++) begin
                folder=$sformatf("output/encoder-vectors/layer_%02d",li);
                $readmemh({folder,"/params.hex"},params);$readmemh({folder,"/w1.hex"},w1);$readmemh({folder,"/w2.hex"},w2);
                $readmemh({folder,"/b1.hex"},b1);$readmemh({folder,"/b2.hex"},b2);$readmemh({folder,"/config.hex"},cfg);
                for(j=0;j<16704;j++) host(0,32'ha0050000+32'(4*j),params[j],rd);
                for(j=0;j<8192;j++) host(0,32'ha0020000+32'(4*j),w1[j],rd);
                for(j=0;j<256;j++) host(0,32'ha0028000+32'(4*j),b1[j],rd);
                for(j=0;j<8192;j++) host(0,32'ha0040000+32'(4*j),w2[j],rd);
                for(j=0;j<64;j++) host(0,32'ha0048000+32'(4*j),b2[j],rd);
                configuration=cfg[1];
                if(!baseline) begin if(li!=0) configuration|=1;if(li!=11) configuration|=2;end
                host(0,32'ha000f008,cfg[0],rd);host(0,32'ha000f00c,configuration,rd);host(0,32'ha000f010,32'(li),rd);
                host(0,32'ha000f000,11,rd);rd=0;n=0;
                while(rd!=2) begin
                    repeat(1024) @(negedge clk);host(1,32'ha000f000,0,rd);n++;
                    if(rd==32'hdead || n>20000) $fatal(1,"Firmware encoder failure task=%0d layer=%0d pc=%h",taskid,li,inspect_pc);
                end
                $display("ENC_LAYER_DONE task=%0d layer=%0d cycle=%0d",taskid,li,cycles);$fflush();
            end
            task_cycles=cycles-start_cycle;total_cycles+=task_cycles;
`ifdef ENCODER_MEMORY_METRICS
            measure=0;
            $display("ENC_MEMORY task=%0d ffn_read16=%0d ffn_write16=%0d shared_read32=%0d shared_write32=%0d ffn_dma_read32=%0d ffn_dma_write32=%0d",taskid,ffn_read16,ffn_write16,shared_read32,shared_write32,ffn_dma_read32,ffn_dma_write32);
`endif
            if($test$plusargs("activity")) $dumpoff;
            $display("ENC_MEASURE_END task=%0d cycle=%0d",taskid,cycles);$fflush();
            host(1,32'ha000f004,0,rd);if(rd!=0) $fatal(1,"Driver status");
            for(j=0;j<6336;j++) begin
                host(1,32'ha0064000+32'(4*j),0,rd);
                if(rd!==expected[j]) $fatal(1,"Encoder output mismatch task=%0d index=%0d got=%h expected=%h",taskid,j,rd,expected[j]);
            end
            for(li=0;li<12;li++) for(j=0;j<8;j++) begin
                host(1,32'ha000f100+32'(32*li+4*j),0,rd);
                if(j==3 && rd!=(li==0 || baseline ? 35712 : 29376)) $fatal(1,"Encoder read count");
                if(j==4 && rd!=(li==11 || baseline ? 9504 : 3168)) $fatal(1,"Encoder write count");
                if(j==7 && rd!=0) $fatal(1,"Encoder saturation");
                $display("ENC_LAYER_STATS task=%0d layer=%0d index=%0d value=%0d",taskid,li,j,rd);
            end
            $display("ENC_SOC_TASK_PASS task=%0d cycles=%0d baseline=%0d outputs=6336",taskid,task_cycles,baseline);$fflush();
        end
        $display("ENC_SOC_PASS tasks=%0d total_cycles=%0d baseline=%0d",num_tasks,total_cycles,baseline);$finish;
    end
endmodule
