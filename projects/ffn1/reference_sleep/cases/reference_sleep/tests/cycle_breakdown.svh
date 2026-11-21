// Simulation-only counters. Bus classes are disjoint; core waits overlap them.
`ifndef KWT_GATE_LEVEL_POWER
    integer timing_bus[0:6], timing_phase[0:6], timing_state[0:9];
    integer timing_idle_phase[0:6];
    integer timing_edges=0,timing_rsp_stall=0,timing_decode_stall=0,timing_writes=0,timing_x_writes=0;
    bit timing_closed=0,timing_w_seen=0,timing_final_seen=0;
    always @(posedge clk) if($test$plusargs("cycle_breakdown")) begin
        if(!measuring) begin
            for(int ti=0;ti<7;ti++) timing_bus[ti]=0;
            for(int ti=0;ti<7;ti++) begin timing_phase[ti]=0;timing_idle_phase[ti]=0;end
            for(int ti=0;ti<10;ti++) timing_state[ti]=0;
            timing_edges=0;timing_rsp_stall=0;timing_decode_stall=0;timing_writes=0;timing_x_writes=0;
            timing_closed=0;timing_w_seen=0;timing_final_seen=0;
        end else if(power_started && !timing_closed) begin
            timing_edges++;
            timing_phase[dut.bus.accelerator.phase]++;
            if(dut.bus.accelerator.phase==4) timing_state[dut.bus.accelerator.tile_engine.core.state]++;
            if(!dut.bus.fabric.accept) begin timing_bus[6]++;timing_idle_phase[dut.bus.accelerator.phase]++;end
            else case(dut.bus.fabric.grant)
                0:timing_bus[0]++;
                1:timing_bus[1]++;
                2:if(!dut.bus.accelerator.m_read) timing_bus[5]++;
                  else case(dut.bus.accelerator.request_target[19:16])
                      4:timing_bus[2]++;
                      3:timing_bus[3]++;
                      1:timing_bus[4]++;
                  endcase
            endcase
            if(dut.bus.fabric.pending && !dut.bus.fabric.response_ready) timing_rsp_stall++;
            if(dut.bus.accelerator.decoder_valid && !dut.bus.accelerator.weight_unpack.out_ready) timing_decode_stall++;
            if(dut.bus.accelerator.decoder_valid && dut.bus.accelerator.weight_unpack.out_ready) begin
                if(dut.bus.accelerator.decoder_x_mode)timing_x_writes++;else timing_writes++;
            end
            if(dut.bus.accelerator.phase==1)
                $display("CYCLE_EVENT task=%0d event=dma_clear cycle=%0d",taskid,cycles);
            if(dut.bus.accelerator.decoder_done && !timing_w_seen && dut.bus.accelerator.phase==2) begin
                timing_w_seen=1;$display("CYCLE_EVENT task=%0d event=weights_done cycle=%0d",taskid,cycles);
            end
            if(dut.bus.accelerator.phase==3)
                $display("CYCLE_EVENT task=%0d event=launch cycle=%0d",taskid,cycles);
            if(dut.bus.accelerator.tile_engine.core.final_group && dut.bus.accelerator.tile_engine.core.push && !timing_final_seen) begin
                timing_final_seen=1;$display("CYCLE_EVENT task=%0d event=final_compute_push cycle=%0d",taskid,cycles);
            end
            if(dut.bus.accelerator.retire && dut.bus.accelerator.phase==4 && !dut.bus.accelerator.outstanding_read &&
               dut.bus.accelerator.write_received==12671 && !dut.bus.accelerator.stopping) begin
                timing_closed=1;
                $display("CYCLE_BUS task=%0d edges=%0d cpu=%0d host=%0d W=%0d B=%0d X=%0d Y=%0d no_accept=%0d rsp_stall=%0d decoded_w_quads=%0d decoded_x_quads=%0d decoder_output_stall=%0d",taskid,
                    timing_edges,timing_bus[0],timing_bus[1],timing_bus[2],timing_bus[3],timing_bus[4],timing_bus[5],timing_bus[6],timing_rsp_stall,timing_writes,timing_x_writes,timing_decode_stall);
                $display("CYCLE_PHASE task=%0d idle=%0d clear=%0d load=%0d launch=%0d run=%0d drain=%0d x_clear=%0d",taskid,
                    timing_phase[0],timing_phase[1],timing_phase[2],timing_phase[3],timing_phase[4],timing_phase[5],timing_phase[6]);
                $display("CYCLE_IDLE_PHASE task=%0d idle=%0d clear=%0d load=%0d launch=%0d run=%0d drain=%0d x_clear=%0d",taskid,
                    timing_idle_phase[0],timing_idle_phase[1],timing_idle_phase[2],timing_idle_phase[3],timing_idle_phase[4],timing_idle_phase[5],timing_idle_phase[6]);
                $display("CYCLE_CORE task=%0d idle=%0d breq=%0d bload=%0d prime=%0d mac=%0d last=%0d pipe=%0d emit=%0d wait_x=%0d drain=%0d",taskid,
                    timing_state[0],timing_state[1],timing_state[2],timing_state[3],timing_state[4],timing_state[5],timing_state[6],timing_state[7],timing_state[8],timing_state[9]);
            end
        end
    end
`endif
