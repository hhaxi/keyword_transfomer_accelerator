// Simulation-only assertions on logical requests to each physical single-port macro.
`ifndef KWT_GATE_LEVEL_POWER
    genvar mon_t,mon_r,mon_p,mon_c;
    generate for(mon_t=0;mon_t<2;mon_t=mon_t+1)begin:monitor_tiles
        for(mon_r=0;mon_r<8;mon_r=mon_r+1)begin:monitor_rows
            for(mon_p=0;mon_p<2;mon_p=mon_p+1)begin:monitor_parities
                wire a=dut.bus.accelerator.tile_engine.core.tiles[mon_t].rows[mon_r].parity[mon_p].raw_wr;
                wire b=dut.bus.accelerator.tile_engine.core.tiles[mon_t].rows[mon_r].parity[mon_p].delta_wr;
                wire c=dut.bus.accelerator.tile_engine.core.tiles[mon_t].rows[mon_r].parity[mon_p].pred_read;
                wire d=dut.bus.accelerator.tile_engine.core.tiles[mon_t].rows[mon_r].parity[mon_p].compute_read;
                always @(posedge clk)if(rst_n && measuring && (int'(a)+int'(b)+int'(c)+int'(d)>1))
                    $fatal(1,"single-port X conflict tile=%0d row=%0d parity=%0d",mon_t,mon_r,mon_p);
            end
        end
    end
    for(mon_c=0;mon_c<8;mon_c=mon_c+1)begin:monitor_columns
        for(mon_p=0;mon_p<2;mon_p=mon_p+1)begin:monitor_w_parities
            always @(posedge clk)if(rst_n && measuring &&
                dut.bus.accelerator.tile_engine.core.columns[mon_c].parity[mon_p].wr &&
                dut.bus.accelerator.tile_engine.core.read_operands)
                $fatal(1,"single-port W conflict column=%0d parity=%0d",mon_c,mon_p);
        end
    end endgenerate
`endif
