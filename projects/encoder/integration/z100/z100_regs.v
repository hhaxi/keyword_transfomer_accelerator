module z100_regs (
    input wire aclk,
    input wire aresetn,
    input wire [11:0] s_axi_awaddr,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,
    input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid,
    output wire s_axi_wready,
    output reg [1:0] s_axi_bresp,
    output reg s_axi_bvalid,
    input wire s_axi_bready,
    input wire [11:0] s_axi_araddr,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output reg [31:0] s_axi_rdata,
    output reg [1:0] s_axi_rresp,
    output reg s_axi_rvalid,
    input wire s_axi_rready
);
    reg address_pending, data_pending;
    reg [11:0] write_address;
    reg [31:0] write_data;
    reg [3:0] write_strobe;
    reg [31:0] scratch, cycles;
    integer lane;

    assign s_axi_awready = !address_pending && !s_axi_bvalid;
    assign s_axi_wready = !data_pending && !s_axi_bvalid;
    assign s_axi_arready = !s_axi_rvalid;

    always @(posedge aclk) begin
        if (!aresetn) begin
            address_pending <= 0;
            data_pending <= 0;
            scratch <= 0;
            cycles <= 0;
            s_axi_bvalid <= 0;
            s_axi_bresp <= 0;
            s_axi_rvalid <= 0;
            s_axi_rresp <= 0;
            s_axi_rdata <= 0;
        end else begin
            cycles <= cycles + 1'b1;
            if (s_axi_awvalid && s_axi_awready) begin
                write_address <= s_axi_awaddr;
                address_pending <= 1;
            end
            if (s_axi_wvalid && s_axi_wready) begin
                write_data <= s_axi_wdata;
                write_strobe <= s_axi_wstrb;
                data_pending <= 1;
            end
            if (s_axi_bvalid && s_axi_bready)
                s_axi_bvalid <= 0;
            if (address_pending && data_pending) begin
                address_pending <= 0;
                data_pending <= 0;
                s_axi_bvalid <= 1;
                s_axi_bresp <= write_address == 12'h008 ? 2'b00 : 2'b10;
                if (write_address == 12'h008) begin
                    for (lane = 0; lane < 4; lane = lane + 1)
                        if (write_strobe[lane])
                            scratch[lane*8 +: 8] <= write_data[lane*8 +: 8];
                end
            end

            if (s_axi_rvalid && s_axi_rready)
                s_axi_rvalid <= 0;
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1;
                s_axi_rresp <= 0;
                case (s_axi_araddr)
                    12'h000: s_axi_rdata <= 32'h4b57545a;
                    12'h004: s_axi_rdata <= 32'h00010000;
                    12'h008: s_axi_rdata <= scratch;
                    12'h00c: s_axi_rdata <= cycles;
                    default: begin
                        s_axi_rdata <= 0;
                        s_axi_rresp <= 2'b10;
                    end
                endcase
            end
        end
    end
endmodule
