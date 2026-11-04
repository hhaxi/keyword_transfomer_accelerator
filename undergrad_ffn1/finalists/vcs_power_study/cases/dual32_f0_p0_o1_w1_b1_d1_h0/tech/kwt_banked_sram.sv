// Native 4096x16 single-port banks. No memory reset or artificial zero fill.
`include "sram_config.vh"
module kwt_banked_sram #(parameter AW=17,DW=32,LIVE_LAST_READ=0)(
    input wire clk,cs,we,input wire [AW-1:0] addr,
    input wire [DW/8-1:0] mask,input wire [DW-1:0] din,
    output wire [DW-1:0] dout
);
    localparam integer BANK_BITS=AW-12;
    localparam integer BANKS=1<<BANK_BITS;
    localparam integer LANES=DW/16;
    wire [DW-1:0] bank_q[0:BANKS-1];
    reg [BANK_BITS-1:0] read_bank;
    reg [AW-1:0] read_addr;
    reg forwarded;
    reg [DW-1:0] forward_data;
    assign dout=LIVE_LAST_READ && forwarded ? forward_data : bank_q[read_bank];
    always @(posedge clk) begin
        if(cs && !we) begin
            read_bank<=addr[AW-1:12];
            read_addr<=addr;
            forwarded<=0;
        end else if(LIVE_LAST_READ && cs && we && addr==read_addr) begin
            // Upstream E203 uses a registered read address with a live array
            // output. Preserve writes to that last-read word using a bypass.
            forwarded<=1;
            for(integer byte_=0;byte_<DW/8;byte_=byte_+1)
                forward_data[8*byte_+:8]<=mask[byte_] ? din[8*byte_+:8] : dout[8*byte_+:8];
        end
    end
    generate
        if(AW<13 || DW%16!=0) begin: unsupported
            KWT_UNSUPPORTED_BANKED_SRAM invalid_configuration();
        end
        for(genvar bank=0;bank<BANKS;bank=bank+1) begin: banks
            for(genvar lane=0;lane<LANES;lane=lane+1) begin: lanes
                wire [15:0] wen={ {8{!mask[2*lane+1]}},{8{!mask[2*lane]}} };
                RAMSP4096X16 u_macro(
                    .Q(bank_q[bank][16*lane+:16]),.CLK(clk),
                    .CEN(!(cs && addr[AW-1:12]==BANK_BITS'(bank))),
                    .WEN(wen),.A(addr[11:0]),.D(din[16*lane+:16]),
                    .EMA(`KWT_SRAM_EMA),.EMAW(`KWT_SRAM_EMAW),
                    .GWEN(!we),.RET1N(1'b1));
            end
        end
    endgenerate
endmodule
