module z100_axi_mmio #(parameter ADDR_WIDTH=16) (
    input wire aclk, aresetn,
    input wire [ADDR_WIDTH-1:0] s_axi_awaddr,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,
    input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid,
    output wire s_axi_wready,
    output wire [1:0] s_axi_bresp,
    output wire s_axi_bvalid,
    input wire s_axi_bready,
    input wire [ADDR_WIDTH-1:0] s_axi_araddr,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output wire [31:0] s_axi_rdata,
    output wire [1:0] s_axi_rresp,
    output wire s_axi_rvalid,
    input wire s_axi_rready,
    output wire cmd_valid,
    input wire cmd_ready,
    output wire [ADDR_WIDTH-1:0] cmd_addr,
    output wire cmd_read,
    output reg [31:0] cmd_wdata,
    output reg [3:0] cmd_wmask,
    input wire rsp_valid,
    output wire rsp_ready,
    input wire [31:0] rsp_data,
    input wire rsp_error
);
    reg aw_pending, w_pending, ar_pending, in_flight, response_read;
    reg [ADDR_WIDTH-1:0] write_address, read_address;
    wire write_complete = aw_pending && w_pending;
    assign s_axi_awready = !aw_pending && !in_flight;
    assign s_axi_wready = !w_pending && !in_flight;
    assign s_axi_arready = !ar_pending && !in_flight && !write_complete;
    assign cmd_valid = !in_flight && (write_complete || ar_pending);
    assign cmd_read = ar_pending;
    assign cmd_addr = cmd_read ? read_address : write_address;
    assign rsp_ready = in_flight && (response_read ? s_axi_rready : s_axi_bready);
    assign s_axi_rvalid = in_flight && rsp_valid && response_read;
    assign s_axi_bvalid = in_flight && rsp_valid && !response_read;
    assign s_axi_rdata = rsp_data;
    assign s_axi_rresp = rsp_error ? 2'b10 : 2'b00;
    assign s_axi_bresp = s_axi_rresp;
    always @(posedge aclk) begin
        if (!aresetn) begin
            aw_pending <= 0;
            w_pending <= 0;
            ar_pending <= 0;
            in_flight <= 0;
            response_read <= 0;
        end else begin
            if (s_axi_awready && s_axi_awvalid) begin
                write_address <= s_axi_awaddr;
                aw_pending <= 1;
            end
            if (s_axi_wready && s_axi_wvalid) begin
                cmd_wdata <= s_axi_wdata;
                cmd_wmask <= s_axi_wstrb;
                w_pending <= 1;
            end
            if (s_axi_arready && s_axi_arvalid) begin
                read_address <= s_axi_araddr;
                ar_pending <= 1;
            end
            if (cmd_valid && cmd_ready) begin
                in_flight <= 1;
                response_read <= cmd_read;
                if (cmd_read) ar_pending <= 0;
                else begin
                    aw_pending <= 0;
                    w_pending <= 0;
                end
            end
            if (rsp_ready && rsp_valid)
                in_flight <= 0;
        end
    end
endmodule
