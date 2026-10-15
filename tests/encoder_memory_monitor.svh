// Observational RTL-only macro pin counters; no changes to synthesizable logic.
`define CORE dut.bus.accelerator.core
wire [39:0] ffn_cs,ffn_we;
genvar mi,mj;
generate
    for(mi=0;mi<2;mi++) begin: monitor_xg
        assign ffn_cs[mi]=`CORE.xbanks[mi].xm.cs;
        assign ffn_we[mi]=`CORE.xbanks[mi].xm.we;
        assign ffn_cs[mi+2]=`CORE.intermediate[mi].gm.cs;
        assign ffn_we[mi+2]=`CORE.intermediate[mi].gm.we;
    end
    for(mi=0;mi<8;mi++) begin: monitor_w
        for(mj=0;mj<2;mj++) begin: monitor_p
            assign ffn_cs[4+mi*2+mj]=`CORE.wbanks[mi].parity[mj].wm.cs;
            assign ffn_we[4+mi*2+mj]=`CORE.wbanks[mi].parity[mj].wm.we;
            assign ffn_cs[20+mi*2+mj]=`CORE.wbanks[mi].second_weights[mj].wm2.cs;
            assign ffn_we[20+mi*2+mj]=`CORE.wbanks[mi].second_weights[mj].wm2.we;
        end
    end
endgenerate
assign ffn_cs[39:36]={`CORE.bm2hi.cs,`CORE.bm2lo.cs,`CORE.bmhi.cs,`CORE.bmlo.cs};
assign ffn_we[39:36]={`CORE.bm2hi.we,`CORE.bm2lo.we,`CORE.bmhi.we,`CORE.bmlo.we};
longint ffn_read16=0,ffn_write16=0,shared_read32=0,shared_write32=0,ffn_dma_read32=0,ffn_dma_write32=0;
always @(posedge clk) begin
    if(!rst_n) begin
        ffn_read16<=0;ffn_write16<=0;shared_read32<=0;shared_write32<=0;ffn_dma_read32<=0;ffn_dma_write32<=0;
    end else if(measure) begin
        ffn_read16<=ffn_read16+64'($countones(ffn_cs & ~ffn_we));
        ffn_write16<=ffn_write16+64'($countones(ffn_cs & ffn_we));
        if(dut.bus.ram_cs) begin
            if(dut.bus.ram_we) shared_write32<=shared_write32+1;
            else shared_read32<=shared_read32+1;
        end
        if(dut.bus.f_valid && dut.bus.f_ready) begin
            if(dut.bus.f_read) ffn_dma_read32<=ffn_dma_read32+1;
            else ffn_dma_write32<=ffn_dma_write32+1;
        end
    end
end
`undef CORE
