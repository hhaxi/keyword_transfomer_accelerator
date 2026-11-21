// Simulation-only, zero-delay hooks in the existing blocking host driver.
// Classes: input write, parameter write, control write, mailbox poll, other.
    integer host_stats=1,host_class=-1;
    initial if($value$plusargs("host_stats=%d",host_stats)) begin end
    longint hc[0:4][0:7],hstart,hage,hpeak[0:4],hcall_peak[0:4];
    longint host_hash,host_calls,host_clock;
    task automatic host_clear;
        begin
            host_class=-1;host_hash=64'hcbf29ce484222325;host_calls=0;host_clock=0;
            for(integer a=0;a<5;a++) begin
                hpeak[a]=0;hcall_peak[a]=0;
                for(integer b=0;b<8;b++) hc[a][b]=0;
            end
        end
    endtask
    task automatic host_enter(input bit rd_,input [31:0] addr_);
        begin
            if(bus_measure && host_stats!=0) begin
                if(!rd_ && addr_>=32'ha0010000) begin
`ifdef HOST_ENCODER
                    host_class=addr_<32'ha0016300 ? 0 : 1;
`else
                    host_class=addr_<32'ha0013180 ? 0 : 1;
`endif
                end else if(!rd_) host_class=2;
                else if(addr_==32'ha000f000) host_class=3;
                else host_class=4;
                hstart=cycles;hage=0;host_calls++;
            end
        end
    endtask
    task automatic host_leave;
        begin
            if(host_class>=0) begin
                if(cycles-hstart>hcall_peak[host_class]) hcall_peak[host_class]=cycles-hstart;
                host_class=-1;
            end
        end
    endtask
    always @(posedge clk) if(rst_n && bus_measure && host_stats!=0 && host_class>=0) begin
        host_clock++;hc[host_class][0]++;
        if(dut.bus.accelerator.active || dut.bus.encoder.busy) hc[host_class][4]++;
        if(dut.bus.accelerator.core.read_operands ||
           (dut.bus.encoder.busy && (dut.bus.encoder.state==dut.bus.encoder.PMAC ||
            dut.bus.encoder.state==dut.bus.encoder.SMAC || dut.bus.encoder.state==dut.bus.encoder.VMAC))) hc[host_class][5]++;
        if(dut.h_valid && !dut.h_ready) begin
            hc[host_class][2]++;hage++;
            if(hage>hpeak[host_class]) hpeak[host_class]=hage;
            if(dut.bus.accelerator.active || dut.bus.encoder.busy) hc[host_class][6]++;
        end
        if(dut.h_valid && dut.h_ready) begin
            hc[host_class][1]++;
            // Ordered non-poll request digest, invariant under timing changes.
            if(host_class!=3) begin
                host_hash=(host_hash ^ {32'b0,dut.h_addr})*64'h100000001b3;
                host_hash=(host_hash ^ {32'b0,dut.h_wdata})*64'h100000001b3;
                host_hash=(host_hash ^ {59'b0,dut.h_mask,dut.h_read})*64'h100000001b3;
            end
        end
        if(dut.h_rsp_valid && dut.h_rsp_ready) hc[host_class][3]++;
        if(dut.c_valid && dut.c_ready && dut.c_read && dut.c_addr==32'ha000f000 &&
           !dut.cpu.u_e203_cpu.u_e203_core.u_e203_biu.buf_icb_cmd_ifu) hc[host_class][7]++;
    end
    task automatic host_report;
        longint count_,elapsed_;
        begin
            if(host_stats!=0 && bus_measure) begin
                count_=0;elapsed_=0;
                for(integer a=0;a<5;a++) begin
                    if(hc[a][1]!=hc[a][3]) $fatal(1,"Host response accounting");
                    count_+=hc[a][1];elapsed_+=hc[a][0];
                    $display("HOST_CLASS task=%0d class=%0d call_cycles=%0d accepted=%0d wait=%0d retired=%0d active_overlap=%0d mac_overlap=%0d wait_overlap=%0d cpu_mailbox_reads=%0d max_wait=%0d max_call=%0d",taskid,a,hc[a][0],hc[a][1],hc[a][2],hc[a][3],hc[a][4],hc[a][5],hc[a][6],hc[a][7],hpeak[a],hcall_peak[a]);
                end
                if(count_!=host_calls || count_!=bc[3][0] || elapsed_!=host_clock || host_class!=-1) $fatal(1,"Host call accounting");
                $display("HOST_ACCOUNTING_PASS task=%0d calls=%0d call_cycles=%0d outside_calls=%0d ordered_hash=%h",taskid,host_calls,host_clock,task_cycles-host_clock,host_hash);
            end
        end
    endtask
`ifdef HOST_ENCODER
    reg [31:0] host_ln2_ref[0:6335];
    integer host_ln2_task=-1,host_ln2_layer=-1,host_ln2_count=0,host_ln2_index;
    always @(posedge clk) if(rst_n && bus_measure && host_stats!=0 && dut.bus.encoder.busy &&
                            dut.bus.encoder.norm_second && dut.bus.encoder.state==dut.bus.encoder.AFFINE) begin
        if(taskid!=host_ln2_task || li!=host_ln2_layer) begin
            $readmemh($sformatf("output/encoder-vectors/task_%02d/layer_%02d/expected.hex",taskid,li),host_ln2_ref);
            host_ln2_task=taskid;host_ln2_layer=li;host_ln2_count=0;
        end
        for(integer lane=0;lane<4;lane++) begin
            host_ln2_index=integer'(dut.bus.encoder.xa)*4+lane;
            if(dut.bus.encoder.xi[lane*32+:32]!==host_ln2_ref[host_ln2_index]) $fatal(1,"Per-layer LN2 mismatch");
        end
        host_ln2_count+=4;
        if(host_ln2_count==6336) $display("HOST_LN2_PASS task=%0d layer=%0d values=%0d",taskid,li,host_ln2_count);
    end
`endif
