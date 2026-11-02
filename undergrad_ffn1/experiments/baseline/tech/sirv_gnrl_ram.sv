// Backend adapter for the pinned E203 generic RAM interface. Upstream sources
// remain unchanged. sd/ds/ls/rst_n have no data effect in the upstream model.
module sirv_gnrl_ram #(
    parameter DP=32,DW=32,FORCE_X2ZERO=1,MW=4,AW=15
)(
    input wire sd,ds,ls,rst_n,clk,cs,we,
    input wire [AW-1:0] addr,input wire [DW-1:0] din,
    input wire [MW-1:0] wem,output wire [DW-1:0] dout
);
    generate
        if(DP!=(1<<AW) || MW!=DW/8 || DW%16!=0 || AW<13) begin: unsupported
            KWT_UNSUPPORTED_CPU_RAM invalid_configuration();
        end
    endgenerate
    // Match the upstream simulation-only X handling: ITCM sets 0, DTCM sets 1.
    // Synthesis always sees the unmodified physical data, as in the upstream RAM.
    wire [DW-1:0] raw_dout;
    kwt_banked_sram #(.AW(AW),.DW(DW),.LIVE_LAST_READ(1)) storage(
        .clk(clk),.cs(cs),.we(we),.addr(addr),.mask(wem),.din(din),.dout(raw_dout));
    generate
        if(FORCE_X2ZERO==1) begin: force_x
            for(genvar bit_=0;bit_<DW;bit_=bit_+1) begin: bits_
`ifndef SYNTHESIS
                assign dout[bit_]=(raw_dout[bit_]===1'bx) ? 1'b0 : raw_dout[bit_];
`else
                assign dout[bit_]=raw_dout[bit_];
`endif
            end
        end else begin: raw_data
            assign dout=raw_dout;
        end
    endgenerate
endmodule
