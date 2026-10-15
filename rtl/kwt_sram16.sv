// Technology boundary: synchronous single-port 16-bit SRAM, no reset of contents.
// Allowed instances use AW=12 (4096), AW=10 (1024), or AW=7 (128).
// KWT_SRAM_BLACKBOX preserves these leaves for official macro mapping.
`ifdef KWT_SRAM_BLACKBOX
(* blackbox *)
`endif
module kwt_sram16 #(parameter AW=12)(
    input wire clk, cs, we,
    input wire [AW-1:0] addr,
    input wire [15:0] din,
    output wire [15:0] dout
);
`ifndef KWT_SRAM_BLACKBOX
    reg [15:0] mem [0:(1<<AW)-1];
    reg [15:0] q;
    assign dout = q;
    always @(posedge clk) if (cs) begin
        if (we) mem[addr] <= din;
        else q <= mem[addr];
    end
`endif
endmodule
