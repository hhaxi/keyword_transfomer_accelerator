// 512 KiB platform SRAM. Account separately from the added accelerator area.
module kwt_shared_sram(
    input wire clk,cs,we,input wire [16:0] addr,input wire [3:0] mask,
    input wire [31:0] din,output wire [31:0] dout
);
    kwt_banked_sram #(.AW(17),.DW(32),.LIVE_LAST_READ(0)) storage(.*);
endmodule
