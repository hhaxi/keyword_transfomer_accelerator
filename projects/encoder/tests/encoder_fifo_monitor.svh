// Observational counters only: sampled at the same edge as RTL handshakes.
// Window: accepted FFN start through successful encoder tail completion.
// No extra CPU MMIO reads, datapath changes or synthesized counter overhead.
`define FM_F dut.bus.accelerator
`define FM_E dut.bus.encoder
`define FM_Q dut.bus.result_fifo
reg fm_active=0,fm_tail_busy=0;
longint fm_empty,fm_full,fm_push,fm_pop,fm_transfer,fm_duplex,fm_peak;
longint fm_tail,fm_initial_wait,fm_between_wait,fm_accept,fm_control,fm_ln,fm_output,fm_other;
longint fm_occupancy[0:4],fm_core_states[0:9];
longint fm_ffn_cycles,fm_mac,fm_parameter_wait;
integer fm_next_count;
always @(posedge clk) begin
    if(!rst_n) fm_active=0;
    else if(`FM_F.start && `FM_F.stream_mode) begin
        fm_active=1;
        fm_empty=0;fm_full=0;fm_push=0;fm_pop=0;fm_transfer=0;fm_duplex=0;fm_peak=0;
        fm_tail=0;fm_initial_wait=0;fm_between_wait=0;fm_accept=0;fm_control=0;fm_ln=0;fm_output=0;fm_other=0;
        fm_ffn_cycles=0;fm_mac=0;fm_parameter_wait=0;
        for(integer c=0;c<5;c++) fm_occupancy[c]=0;
        for(integer c=0;c<10;c++) fm_core_states[c]=0;
        if(`FM_Q.count!=0) $fatal(1,"Stale FIFO at FFN start");
    end else if(fm_active) begin
        if(`FM_Q.clear) $fatal(1,"Unexpected cancellation in successful SoC profile");
        if(fm_push-fm_pop!=64'(`FM_Q.count)) $fatal(1,"FIFO occupancy conservation");
        fm_occupancy[`FM_Q.count]++;
        if(`FM_Q.out_ready && !`FM_Q.out_valid) fm_empty++;
        if(`FM_Q.in_valid && !`FM_Q.in_ready) fm_full++;
        if(`FM_Q.push) fm_push++;
        if(`FM_Q.pop) fm_pop++;
        if(`FM_Q.push || `FM_Q.pop) fm_transfer++;
        if(`FM_Q.push && `FM_Q.pop) fm_duplex++;
        fm_next_count=int'(`FM_Q.count)+int'(`FM_Q.push)-int'(`FM_Q.pop);
        if(fm_next_count>fm_peak) fm_peak=64'(fm_next_count);
        if(`FM_F.active) fm_ffn_cycles++;
        if(`FM_F.core.busy) fm_core_states[`FM_F.core.state]++;
        if(`FM_F.core.mac_enable) fm_mac++;
        if(`FM_F.core.state==`FM_F.core.GELU && !`FM_F.core.gelu_busy && !`FM_F.core.second_ready) fm_parameter_wait++;
        if(`FM_E.busy && `FM_E.operation==1) begin
            fm_tail++;
            if(`FM_E.state==`FM_E.TSTREAM) begin
                if(`FM_E.result_fire) fm_accept++;
                else if(fm_pop==0) fm_initial_wait++;
                else fm_between_wait++;
            end else if(`FM_E.state==`FM_E.TGROUP || `FM_E.state==`FM_E.TSTORE) fm_control++;
            else if(`FM_E.state>=`FM_E.SUMINIT && `FM_E.state<=`FM_E.AFFINE) fm_ln++;
            else if(`FM_E.state>=`FM_E.DREAD && `FM_E.state<=`FM_E.WWAIT) fm_output++;
            else fm_other++;
        end
    end
end
always @(negedge clk) begin
    if(!rst_n) fm_tail_busy=0;
    else begin
        if(fm_active && fm_tail_busy && !`FM_E.busy) begin
            if(!`FM_E.done || `FM_E.error || `FM_E.aborted) $fatal(1,"Profile ended without success");
            if(fm_push!=6336 || fm_pop!=6336 || `FM_Q.count!=0 || fm_peak>4) $fatal(1,"FIFO transfer count");
            if(fm_transfer+fm_duplex!=fm_push+fm_pop || fm_empty!=fm_initial_wait+fm_between_wait) $fatal(1,"Handshake counter conservation");
            if(fm_tail!=64'(`FM_E.cycles) || fm_tail!=fm_initial_wait+fm_between_wait+fm_accept+fm_control+fm_ln+fm_output+fm_other || fm_other!=0) $fatal(1,"Tail partition");
            if(fm_ffn_cycles!=64'(`FM_F.total_cycles) || fm_mac!=202752) $fatal(1,"FFN profile conservation");
            $display("FIFO_PROFILE task=%0d layer=%0d empty_wait=%0d full_wait=%0d push=%0d pop=%0d transfer_cycles=%0d duplex=%0d peak=%0d tail_total=%0d initial_wait=%0d between_wait=%0d accept=%0d residual_control=%0d ln2=%0d output=%0d other=%0d ffn_cycles=%0d mac=%0d parameter_wait=%0d",taskid,li,fm_empty,fm_full,fm_push,fm_pop,fm_transfer,fm_duplex,fm_peak,fm_tail,fm_initial_wait,fm_between_wait,fm_accept,fm_control,fm_ln,fm_output,fm_other,fm_ffn_cycles,fm_mac,fm_parameter_wait);
            for(integer c=0;c<5;c++) $display("FIFO_OCCUPANCY task=%0d layer=%0d count=%0d cycles=%0d",taskid,li,c,fm_occupancy[c]);
            for(integer c=0;c<10;c++) $display("FFN_STATE task=%0d layer=%0d state=%0d cycles=%0d",taskid,li,c,fm_core_states[c]);
            $fflush();fm_active=0;
        end
        fm_tail_busy=`FM_E.busy && `FM_E.operation==1;
    end
end
`undef FM_F
`undef FM_E
`undef FM_Q
