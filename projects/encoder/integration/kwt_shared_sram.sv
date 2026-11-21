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
`ifdef KWT_FPGA_BANKED_SHARED
    // Keep the logical single port while breaking the long FPGA BRAM cascade.
    // A 1K x 32 bank maps to one RAMB36 with native byte write enables.
    reg [6:0] read_bank;
    wire [31:0] read_data[0:127];
    assign dout=read_data[read_bank];
    always @(posedge clk) if(cs && !we) read_bank<=addr[16:10];
    for(genvar bank=0;bank<128;bank=bank+1) begin: banks
        (* ram_style="block" *) reg [31:0] mem[0:1023];
        reg [31:0] q;
        assign read_data[bank]=q;
        always @(posedge clk) if(cs && addr[16:10]==7'(bank)) begin
            if(we) begin
                for(integer lane=0;lane<4;lane=lane+1)
                    if(mask[lane]) mem[addr[9:0]][8*lane+:8]<=din[8*lane+:8];
            end else q<=mem[addr[9:0]];
        end
    end
`else
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
`endif
endmodule
