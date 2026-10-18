// Testbench-only observation. Source IDs: IFU, CPU status, CPU other, host,
// FFN read/write, encoder read/write. An offered request has ONE cause each clock.
`define BF dut.bus.fabric
`define BA dut.bus.dma_arbiter
`define BI dut.cpu.u_e203_cpu.u_e203_core.u_e203_biu
    integer bus_stats=1;
    initial if($value$plusargs("bus_stats=%d",bus_stats)) begin end
    reg bus_measure=0;
    longint bus_ticks=0,bc[0:7][0:12],bw[0:10][0:12],bs[0:7][0:2];
    longint bage[0:3],bmax[0:7],bslot_idle,bslot_refill,bunion,bcritical;
    integer bsrc[0:3],bselected,bslot_src=0,bwhy,bwin;
    reg [3:0] bvalid,bready;
    reg any_stall,critical_stall;
    function automatic integer cpu_source;
        if(`BI.buf_icb_cmd_ifu) cpu_source=0;
        else if(dut.c_read && (dut.c_addr==32'h40000004 || dut.c_addr==32'h40080004)) cpu_source=1;
        else cpu_source=2;
    endfunction
    `include "host_study_monitor.svh"
    task automatic bus_begin;
        begin
            host_clear();
            bus_measure=bus_stats!=0;bus_ticks=0;bslot_idle=0;bslot_refill=0;bunion=0;bcritical=0;
            for(integer s=0;s<8;s++) begin
                bmax[s]=0;
                for(integer c=0;c<13;c++) bc[s][c]=0;
                for(integer c=0;c<3;c++) bs[s][c]=0;
            end
            for(integer s=0;s<11;s++) for(integer c=0;c<13;c++) bw[s][c]=0;
            for(integer m=0;m<4;m++) bage[m]=0;
        end
    endtask
    always @(posedge clk) begin
        if(!rst_n) bslot_src=0;
        else begin
            bsrc[0]=cpu_source();bsrc[1]=3;
            bsrc[2]=dut.bus.f_read ? 4 : 5;bsrc[3]=dut.bus.e_read ? 6 : 7;
            bvalid={dut.bus.e_valid,dut.bus.f_valid,dut.h_valid,dut.c_valid};
            bready={dut.bus.e_ready,dut.bus.f_ready,dut.h_ready,dut.c_ready};
            bselected=`BF.grant==0 ? bsrc[0] : `BF.grant==1 ? 3 : (`BA.grant ? bsrc[3] : bsrc[2]);
            if(bus_measure) begin
                bus_ticks++;any_stall=0;critical_stall=0;
                if(dut.c_valid && (`BI.buf_icb_cmd_addr!==dut.c_addr || !`BI.buf_icb_cmd_valid))
                    $fatal(1,"CPU source tag is not aligned to external command");
                if(!`BF.pending) bslot_idle++;
                else if(!`BF.response_valid) bs[bslot_src][0]++;
                else if(!`BF.response_ready) bs[bslot_src][1]++;
                else bs[bslot_src][2]++;
                if(`BF.retire && `BF.accept) bslot_refill++;
                for(integer m=0;m<4;m++) begin
                    if(!bvalid[m]) bage[m]=0;
                    else begin
                        // Priority: response-slot root cause before arbitration.
                        if(bready[m]) bwhy=0;
                        else if(!`BF.slot_free) bwhy=`BF.response_valid ? 2 : 1;
                        else if(m>=2 && !`BA.free_) bwhy=4;
                        else if(m>=2 && `BA.grant!=(m==3)) bwhy=5;
                        else if(`BF.grant!=(m<2 ? m : 2)) begin
                            case(bselected)
                                0:bwhy=6;1:bwhy=7;2:bwhy=8;3:bwhy=9;
                                4,5:bwhy=10;6,7:bwhy=11;
                                default:bwhy=12;
                            endcase
                        end else if(`BF.sel_acc && !`BF.a_ready) bwhy=3;
                        else bwhy=12;
                        if(bwhy==12) $fatal(1,"Unclassified bus stall master=%0d",m);
                        bc[bsrc[m]][bwhy]++;
                        if(bwhy==0) bage[m]=0;
                        else begin
                            bage[m]++;any_stall=1;
                            if(bage[m]>bmax[bsrc[m]]) bmax[bsrc[m]]=bage[m];
                        end
                        bwin=-1;
                        if(m==2) bwin=!dut.bus.f_read ? 2 : dut.bus.accelerator.phase==dut.bus.accelerator.LOAD ? 0 : 1;
                        if(m==3) begin
                            if(dut.bus.encoder.loading) bwin=dut.bus.encoder.load_kind<2 ? 3+integer'(dut.bus.encoder.load_kind) : 5+integer'(dut.bus.encoder.projection);
                            else bwin=dut.bus.encoder.dumping ? 9 : 10;
                        end
                        if(bwin>=0) bw[bwin][bwhy]++;
                        // Conservative serial windows: FFN initial load and
                        // encoder DMA (exclude overlapped W2/preload/output writes).
                        if(bwhy!=0 && (m==3 || (m==2 && bwin==0 && !dut.bus.accelerator.input_mode))) critical_stall=1;
                    end
                end
                if(any_stall) bunion++;
                if(critical_stall) bcritical++;
            end
            if(`BF.accept) bslot_src=bselected;
        end
    end
    task automatic bus_end;
        longint occupied;
        begin
            host_report();
            bus_measure=0;
            if(bus_stats!=0) begin
                occupied=bslot_idle;
                for(integer s=0;s<8;s++) begin
                    for(integer c=0;c<3;c++) occupied+=bs[s][c];
                    $display("BUS_SOURCE task=%0d source=%0d accepted=%0d slot_target=%0d slot_sink=%0d target=%0d dma_slot=%0d dma_peer=%0d grant_ifu=%0d grant_poll=%0d grant_cpu=%0d grant_host=%0d grant_ffn=%0d grant_enc=%0d other=%0d max_wait=%0d",taskid,s,bc[s][0],bc[s][1],bc[s][2],bc[s][3],bc[s][4],bc[s][5],bc[s][6],bc[s][7],bc[s][8],bc[s][9],bc[s][10],bc[s][11],bc[s][12],bmax[s]);
                    $display("BUS_SLOT task=%0d source=%0d target=%0d sink=%0d retire=%0d",taskid,s,bs[s][0],bs[s][1],bs[s][2]);
                end
                for(integer s=0;s<11;s++)
                    $display("BUS_WINDOW task=%0d window=%0d accepted=%0d slot_target=%0d slot_sink=%0d target=%0d dma_slot=%0d dma_peer=%0d grant_ifu=%0d grant_poll=%0d grant_cpu=%0d grant_host=%0d grant_ffn=%0d grant_enc=%0d other=%0d",taskid,s,bw[s][0],bw[s][1],bw[s][2],bw[s][3],bw[s][4],bw[s][5],bw[s][6],bw[s][7],bw[s][8],bw[s][9],bw[s][10],bw[s][11],bw[s][12]);
                if(occupied!=bus_ticks || bus_ticks!=task_cycles) $fatal(1,"Bus accounting window mismatch");
                $display("BUS_ACCOUNTING_PASS task=%0d cycles=%0d slot_idle=%0d retire_refill=%0d stall_union=%0d serial_dma_stall_union=%0d",taskid,bus_ticks,bslot_idle,bslot_refill,bunion,bcritical);
            end
        end
    endtask
`undef BF
`undef BA
`undef BI
