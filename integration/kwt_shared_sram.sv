// 512 KiB shared system SRAM model/boundary, excluded from accelerator area.
`ifdef KWT_SRAM_BLACKBOX
(* blackbox *)
`endif
module kwt_shared_sram(
    input wire clk, cs, we,
    input wire [16:0] addr,
    input wire [3:0] mask,
    input wire [31:0] din,
    output wire [31:0] dout
);
`ifndef KWT_SRAM_BLACKBOX
    reg [31:0] mem [0:131071];
    reg [31:0] q;
    assign dout=q;
    integer i;
    always @(posedge clk) if(cs) begin
        if(we) begin
            for(i=0;i<4;i=i+1) if(mask[i]) mem[addr][8*i+:8]<=din[8*i+:8];
        end else q<=mem[addr];
    end
`endif
endmodule
