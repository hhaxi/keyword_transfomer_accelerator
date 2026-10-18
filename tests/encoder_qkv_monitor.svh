// Simulation only. Exclusive state buckets and overlapping port/DMA events
// are deliberately reported separately. No force, delays or DUT writes.
`define QE dut.bus.encoder
    integer qkv_stats=1;
    initial if($value$plusargs("qkv_stats=%d",qkv_stats)) begin end
    longint qs[0:2][0:4]; // MAC, prime, init, save, other/wait
    longint qr[0:2][0:5]; // X words, W words, result words, MAC prefetch,
                          // save prefetch, free W-port cycles on final row
    longint ql[0:5][0:9]; // cycles, issue-only, retire-only, both, neither,
                          // request stall, response wait, credit-full, writes, FFN issue
    reg [31:0] qref[0:6335],kref[0:6335],vref[0:6335];
    reg q_counting=0,q_was_busy=0;
    integer qp,qb,qi_,qidx;
    longint qsum,lsum;
    always @(posedge clk) begin
        if(!rst_n || !`QE.busy) q_counting=0;
        if(rst_n && qkv_stats!=0 && `QE.busy && `QE.operation==0) begin
            if(!q_counting) begin
                for(integer p=0;p<3;p++) begin
                    for(integer b=0;b<5;b++) qs[p][b]=0;
                    for(integer b=0;b<6;b++) qr[p][b]=0;
                end
                for(integer p=0;p<6;p++) for(integer b=0;b<10;b++) ql[p][b]=0;
                $readmemh($sformatf("output/encoder-vectors/task_%02d/layer_%02d/q.hex",taskid,li),qref);
                $readmemh($sformatf("output/encoder-vectors/task_%02d/layer_%02d/k.hex",taskid,li),kref);
                $readmemh($sformatf("output/encoder-vectors/task_%02d/layer_%02d/v.hex",taskid,li),vref);
                q_counting=1;
            end
            if(`QE.stopping) $fatal(1,"QKV study requires a completed, non-aborted command");
            qp=integer'(`QE.projection);
            if(qp<3 && `QE.state>=`QE.PINIT && `QE.state<=`QE.RSAVE) begin
                case(`QE.state)
                    `QE.PMAC: qb=0;
                    `QE.PPRIME: qb=1;
                    `QE.PINIT: qb=2;
                    `QE.PSAVE: qb=3;
                    default: qb=4;
                endcase
                qs[qp][qb]++;
                if(`QE.xcs && !`QE.xwe) qr[qp][0]+=64'(`QE.pop4(`QE.xm));
                if(`QE.wcs && !`QE.wwe) qr[qp][1]+=64'(`QE.pop4(`QE.wm));
                if(`QE.wcs && !`QE.wwe && `QE.state==`QE.PMAC) qr[qp][3]++;
                if(`QE.wcs && !`QE.wwe && `QE.state==`QE.PSAVE) qr[qp][4]++;
                if(!`QE.wcs && `QE.row==98) qr[qp][5]++;
                if(`QE.state==`QE.PSAVE) begin
                    qr[qp][2]+=4;
                    for(integer t=0;t<4;t++) begin
                        qidx=integer'(`QE.row)*64+integer'(`QE.group_)*4+t;
                        if(qp==0 && `QE.qi[t*32+:32]!==qref[qidx]) $fatal(1,"QKV study Q mismatch");
                        if(qp==1 && `QE.ki[t*32+:32]!==kref[qidx]) $fatal(1,"QKV study K mismatch");
                        if(qp==2 && `QE.vi[t*32+:32]!==vref[qidx]) $fatal(1,"QKV study V mismatch");
                    end
                end
            end
            if(`QE.loading) begin
                qi_=integer'(`QE.load_kind)<2 ? integer'(`QE.load_kind) : 2+qp;
                ql[qi_][0]++;
                case({`QE.issue,`QE.retire})
                    2'b10: ql[qi_][1]++;
                    2'b01: ql[qi_][2]++;
                    2'b11: ql[qi_][3]++;
                    2'b00: ql[qi_][4]++;
                endcase
                if(`QE.m_valid && !`QE.m_ready) ql[qi_][5]++;
                if(`QE.pending_count!=0 && !`QE.m_rsp_valid) ql[qi_][6]++;
                if(`QE.pending_count==2 && `QE.issue_index<`QE.load_length) ql[qi_][7]++;
                if(`QE.retire && !`QE.m_err) ql[qi_][8]++;
                if(dut.bus.accelerator.m_valid && dut.bus.accelerator.m_ready) ql[qi_][9]++;
            end
        end
    end
    always @(negedge clk) begin
        if(rst_n && qkv_stats!=0 && q_was_busy && !`QE.busy && `QE.operation==0) begin
            qsum=0;lsum=0;
            for(integer p=0;p<3;p++) begin
                for(integer b=0;b<5;b++) qsum+=qs[p][b];
                if(qs[p][0]!=101376 || qs[p][1]!=1 || qs[p][2]!=1 || qs[p][3]!=1584 || qs[p][4]!=0)
                    $fatal(1,"QKV exclusive accounting mismatch");
                if(qr[p][0]!=101376 || qr[p][1]!=405504 || qr[p][2]!=6336 || qr[p][3]!=99792 || qr[p][4]!=1583 || qr[p][5]!=17)
                    $fatal(1,"QKV port accounting mismatch");
                $display("QKV_COMPUTE task=%0d layer=%0d projection=%0d mac=%0d prime=%0d init=%0d save=%0d wait=%0d x_read32=%0d w_read32=%0d result_write32=%0d prefetch_mac=%0d prefetch_save=%0d final_row_w_idle=%0d",taskid,li,p,qs[p][0],qs[p][1],qs[p][2],qs[p][3],qs[p][4],qr[p][0],qr[p][1],qr[p][2],qr[p][3],qr[p][4],qr[p][5]);
            end
            for(integer p=0;p<6;p++) begin
                lsum+=ql[p][0];
                if(ql[p][0]!=ql[p][1]+ql[p][2]+ql[p][3]+ql[p][4] || ql[p][1]!=ql[p][2] || ql[p][8]!=ql[p][2]+ql[p][3])
                    $fatal(1,"QKV DMA partition mismatch");
                $display("QKV_LOAD task=%0d layer=%0d kind=%0d cycles=%0d issue_only=%0d retire_only=%0d both=%0d neither=%0d request_stall=%0d response_wait=%0d credit_full=%0d write32=%0d ffn_issues=%0d",taskid,li,p,ql[p][0],ql[p][1],ql[p][2],ql[p][3],ql[p][4],ql[p][5],ql[p][6],ql[p][7],ql[p][8],ql[p][9]);
            end
            if(qsum!=64'(`QE.phase_cycles[0]) || lsum!=64'(`QE.phase_cycles[7])) $fatal(1,"QKV hardware phase mismatch");
            $display("QKV_ACCOUNTING_PASS task=%0d layer=%0d phase=%0d load=%0d checked_values=19008",taskid,li,qsum,lsum);
        end
        q_was_busy=rst_n && `QE.busy;
    end
`undef QE
