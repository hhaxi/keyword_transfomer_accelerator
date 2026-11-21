`timescale 1ns/1ps
module tb_encoder_faults;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cmd_valid=0,cmd_read=0,rsp_ready=1;
    reg [19:0] cmd_addr=0;reg [31:0] cmd_wdata=0;reg [3:0] cmd_wmask=15;
    wire cmd_ready,rsp_valid,rsp_err;wire [31:0] rsp_rdata;
    wire m_valid,m_read,m_rsp_ready;wire [31:0] m_addr,m_wdata;wire [3:0] m_mask;
    reg block_request=0,block_response=0,inject_read_error=0,inject_write_error=0;
    integer queued=0;reg head=0,tail=0;
    reg response_error[0:1];reg [31:0] response_data[0:1];
    wire pending=queued!=0;
    wire m_ready=queued<2 && !block_request;
    wire m_rsp_valid=pending && !block_response;
    wire [31:0] m_rdata=response_data[head];wire m_err=response_error[head];
    reg last_write_accepted=0,offer_stalled=0;reg [31:0] stable_addr,stable_data;reg stable_read;
    reg [31:0] mem[0:131071],params[0:16703],initial_x[0:6335],packed_x[0:3167],cfg[0:1],rd;
    integer cycles=0,accepted=0,written=0,j,snapshot_;reg [31:0] held_addr,held_data;
    kwt_encoder dut(.preload_permit(),.input_valid(),.input_ready(1'b0),.input_data(),.result_valid(1'b0),.result_ready(),.result_data(40'd0),.link_abort_in(1'b0),.link_abort_out(),.*);
    always @(posedge clk) begin
        cycles<=cycles+1;if(cycles>12000000) $fatal(1,"Fault test timeout state=%d",dut.state);
        if(!rst_n) begin queued<=0;head<=0;tail<=0;offer_stalled<=0;last_write_accepted<=0;end
        else begin
            if(offer_stalled && (!m_valid || m_addr!==stable_addr || m_wdata!==stable_data || m_read!==stable_read)) $fatal(1,"Offered DMA withdrawn/changed");
            offer_stalled<=m_valid && !m_ready;stable_addr<=m_addr;stable_data<=m_wdata;stable_read<=m_read;
            case({m_valid && m_ready,m_rsp_valid && m_rsp_ready})
                2'b10:queued<=queued+1;
                2'b01:queued<=queued-1;
                default:begin end
            endcase
            if(m_valid && m_ready) begin
                response_data[tail]<=mem[m_addr[18:2]];
                response_error[tail]<=m_read ? inject_read_error : inject_write_error;
                tail<=!tail;accepted<=accepted+1;
                if(!m_read) begin
                    mem[m_addr[18:2]]<=m_wdata;written<=written+1;
                    if(m_addr=='ha001b17c) last_write_accepted<=1;
                end
            end
            if(m_rsp_valid && m_rsp_ready) head<=!head;
            if(!dut.busy && queued!=0) $fatal(1,"Idle with undrained DMA");
        end
    end
    task automatic bus(input bit read_,input [19:0] addr,input [31:0] data,input bit expect_error);
        begin
            @(negedge clk);cmd_valid=1;cmd_read=read_;cmd_addr=addr;cmd_wdata=data;
            do @(posedge clk);while(!cmd_ready);
            @(negedge clk);cmd_valid=0;
            while(!rsp_valid) @(negedge clk);
            if(rsp_err!==expect_error) $fatal(1,"Unexpected register response addr=%h err=%b",addr,rsp_err);
            rd=rsp_rdata;
        end
    endtask
    task automatic configure;
        begin
            bus(0,0,4,0);bus(0,'h20,'ha0010000,0);bus(0,'h24,'ha0050000,0);
            bus(0,'h28,'ha0018000,0);bus(0,'h2c,'ha0030000,0);bus(0,'h30,'ha0064000,0);
            bus(0,'h34,cfg[1],0);bus(0,'h38,0,0);
        end
    endtask
    task automatic wait_idle;
        begin
            rd=1;while(rd[0]) begin repeat(100) @(negedge clk);bus(1,4,0,0);end
        end
    endtask
    task automatic check_invalid;
        begin
            snapshot_=accepted;bus(0,0,1,1);repeat(10) @(negedge clk);
            bus(1,4,0,0);if(rd[0] || !rd[4] || accepted!=snapshot_) $fatal(1,"Invalid config issued DMA");
        end
    endtask
    task automatic check_aborted;
        begin
            wait_idle();if(rd[6:5]!=0 || !rd[3] || rd[1]) $fatal(1,"Abort validity/done status=%h",rd);
            bus(0,'h34,cfg[1]|1,0);check_invalid();
        end
    endtask
    initial begin
        $readmemh("output/encoder-vectors/task_00/input.hex",initial_x);
        $readmemh("output/encoder-vectors/layer_00/params.hex",params);
        $readmemh("output/encoder-vectors/layer_00/config.hex",cfg);
        $readmemh("output/encoder-vectors/task_00/layer_00/ffn_input.hex",packed_x);
        for(j=0;j<6336;j++) mem[16384+j]=initial_x[j];
        for(j=0;j<16704;j++) mem[81920+j]=params[j];
        repeat(4) @(negedge clk);rst_n=1;configure();
        bus(0,'h20,'ha0010001,0);check_invalid();configure();
        bus(0,'h24,'ha0070000,0);check_invalid();configure();
        bus(0,'h28,'ha0050000,0);check_invalid();configure();
        bus(0,'h34,cfg[1]|16,0);check_invalid();configure();
        bus(0,'h34,cfg[1]|1,0);check_invalid();configure();
        bus(0,'h38,1,0);check_invalid();configure();
        cmd_wmask=3;bus(0,'h20,'ha0010000,1);cmd_wmask=15;
        bus(1,'h21,0,1);configure();
        // Stalled register response remains stable and blocks a second request.
        @(negedge clk);rsp_ready=0;bus(1,'hc,0,0);held_data=rd;
        repeat(10) begin @(negedge clk);if(!rsp_valid || cmd_ready || rsp_rdata!==held_data || rsp_err) $fatal(1,"Register response stability");end
        rsp_ready=1;@(negedge clk);
        $display("FAULT_STAGE register_checks");$fflush();
        // Abort must preserve an offered request until accepted, then drain its response.
        block_request=1;block_response=1;bus(0,0,1,0);while(!m_valid) @(negedge clk);held_addr=m_addr;
        bus(0,'h20,'ha0020000,1);if(dut.xbase!='ha0010000) $fatal(1,"Busy config changed");
        bus(0,0,2,0);
        repeat(12) begin @(negedge clk);if(!m_valid || m_addr!==held_addr || !dut.busy) $fatal(1,"Aborted offer withdrawn");end
        block_request=0;while(!pending) @(negedge clk);
        repeat(12) begin @(negedge clk);if(!dut.busy || dut.done) $fatal(1,"Abort failed to drain");end
        block_response=0;check_aborted();configure();
        $display("FAULT_STAGE abort_offer_drain");$fflush();
        // Accepted read response error invalidates all retained state.
        inject_read_error=1;bus(0,0,1,0);wait_idle();
        if(!rd[2] || rd[6:5]!=0 || rd[1]) $fatal(1,"Read fault state");inject_read_error=0;configure();
        $display("FAULT_STAGE read_error");$fflush();
        // Abort with two accepted reads: the first response cannot end draining.
        block_response=1;bus(0,0,1,0);while(queued!=2) @(negedge clk);
        bus(0,0,2,0);snapshot_=accepted;
        block_response=0;@(negedge clk);block_response=1;
        repeat(8) begin @(negedge clk);if(!dut.busy || queued!=1 || m_valid) $fatal(1,"Multi-response abort drain");end
        block_response=0;check_aborted();if(accepted!=snapshot_) $fatal(1,"Extra abort issue");configure();
        // First response errors while a second request is held by backpressure.
        inject_read_error=1;block_response=1;bus(0,0,1,0);
        while(queued==0) @(negedge clk);block_request=1;
        while(!m_valid) @(negedge clk);repeat(3) @(negedge clk);
        held_addr=m_addr;block_response=0;@(negedge clk);block_response=1;
        repeat(8) begin @(negedge clk);if(!dut.busy || !m_valid || m_addr!==held_addr) $fatal(1,"Error withdrew offer");end
        inject_read_error=0;block_request=0;while(queued==0) @(negedge clk);
        repeat(8) begin @(negedge clk);if(!dut.busy || dut.done) $fatal(1,"Error failed to drain later request");end
        block_response=0;wait_idle();if(!rd[2] || rd[1] || queued!=0) $fatal(1,"Error drain status");configure();
        $display("FAULT_STAGE two_outstanding_abort_error_held_offer");$fflush();
        // Abort a running arithmetic helper, then ensure no delayed completion survives.
        bus(0,0,1,0);while(!dut.sqrt_busy) @(negedge clk);bus(0,0,2,0);check_aborted();
        repeat(100) @(negedge clk);if(dut.sqrt_busy || dut.div_busy || dut.done) $fatal(1,"Math abort");configure();
        $display("FAULT_STAGE math_abort");$fflush();
        // Reset during an accepted transfer; global reset clears fabric + accelerator.
        block_response=1;bus(0,0,1,0);while(!pending) @(negedge clk);
        rst_n=0;repeat(4) @(negedge clk);rst_n=1;block_response=0;
        bus(1,4,0,0);if(rd!=0 || m_valid) $fatal(1,"Reset validity");configure();
        // Full clean restart, followed by a delayed/error final write acknowledgement.
        written=0;bus(0,0,1,0);
        while(!(m_valid && !m_read && m_addr=='ha001b17c)) @(negedge clk);
        block_response=1;inject_write_error=1;
        while(!last_write_accepted) @(negedge clk);
        repeat(20) begin @(negedge clk);if(!dut.busy || dut.done) $fatal(1,"Early done before final acknowledgement");end
        block_response=0;wait_idle();inject_write_error=0;
        if(!rd[2] || rd[1] || rd[6:5]!=0) $fatal(1,"Final write error validity");configure();
        bus(0,0,1,0);wait_idle();if(!rd[1] || !rd[6] || rd[4:2]!=0) $fatal(1,"Clean restart status=%h",rd);
        for(j=0;j<3168;j++) if(mem[24576+j]!==packed_x[j]) $fatal(1,"Clean restart value %0d",j);
        $display("ENC_FAULTS_PASS config busy response_stall abort_offer abort_drain read_error math_abort reset final_write_error restart two_outstanding error_held_offer");$finish;
    end
endmodule
