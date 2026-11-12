module z100_kwt #(parameter FAST_PROJECTION = 0, parameter FAST_ATTENTION = 0, parameter FAST_FFN_ROWS = 0,
    parameter FAST_HANDOFF = 0, parameter GELU_CYCLES = 1) (
    input wire aclk, aresetn,
    input wire [15:0] s_axi_awaddr,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,
    input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid,
    output wire s_axi_wready,
    output wire [1:0] s_axi_bresp,
    output wire s_axi_bvalid,
    input wire s_axi_bready,
    input wire [15:0] s_axi_araddr,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output wire [31:0] s_axi_rdata,
    output wire [1:0] s_axi_rresp,
    output wire s_axi_rvalid,
    input wire s_axi_rready,
    output wire [31:0] m_axi_awaddr,
    output wire [7:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
    output wire m_axi_awvalid,
    input wire m_axi_awready,
    output wire [31:0] m_axi_wdata,
    output wire [3:0] m_axi_wstrb,
    output wire m_axi_wlast,
    output wire m_axi_wvalid,
    input wire m_axi_wready,
    input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready,
    output wire [31:0] m_axi_araddr,
    output wire [7:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire [31:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast,
    input wire m_axi_rvalid,
    output wire m_axi_rready
);
    wire cmd_valid, cmd_ready, cmd_read;
    wire [15:0] cmd_addr;
    wire [31:0] cmd_wdata;
    wire [3:0] cmd_wmask;
    wire rsp_valid, rsp_ready, rsp_error;
    wire [31:0] rsp_data;
    wire f_cmd_ready, f_rsp_valid, f_rsp_error, e_cmd_ready, e_rsp_valid, e_rsp_error;
    wire [31:0] f_rsp_data, e_rsp_data;
    wire select_ffn = cmd_addr[15:12] == 1;
    wire select_encoder = cmd_addr[15:12] == 2;
    reg [1:0] response_target;
    wire select_model = cmd_addr == 16'h3000;
    wire select_model_id = cmd_addr == 16'h3004 && cmd_read;
    wire select_features = cmd_addr == 16'h3008 && cmd_read;
    reg local_response, local_error;
    reg [31:0] local_data, model_base;
    wire model_address_ok = cmd_wdata == 0 ||
        (cmd_wdata[1:0] == 0 && cmd_wdata >= 32'h11000010 &&
         cmd_wdata <= 32'h11000010 + 32'd1470040);
    wire model_write = cmd_valid && cmd_ready && select_model && !cmd_read &&
        cmd_wmask == 4'hf && model_address_ok;

    wire f_valid, f_ready, f_read, f_ddr_valid, f_error;
    wire e_valid, e_ready, e_read, e_ddr_valid, e_ddr_ready, e_error;
    wire [31:0] f_addr, f_data, f_ddr_data, e_addr, e_data, e_ddr_data;
    wire [3:0] e_mask;
    wire d_valid, d_ready, d_read, d_rsp_valid, d_rsp_ready, d_error;
    wire [31:0] d_addr, d_data, d_rsp_data;
    wire [3:0] d_mask;
    wire preload_permit, input_valid, input_ready, result_valid, result_ready, link_error;
    wire [31:0] input_data;
    wire [39:0] result_data;

    assign cmd_ready = select_ffn ? f_cmd_ready : select_encoder ? e_cmd_ready : !local_response;
    assign rsp_valid = response_target == 1 ? f_rsp_valid :
        response_target == 2 ? e_rsp_valid : local_response;
    assign rsp_data = response_target == 1 ? f_rsp_data : response_target == 2 ? e_rsp_data : local_data;
    assign rsp_error = response_target == 1 ? f_rsp_error :
        response_target == 2 ? e_rsp_error : local_error;

    always @(posedge aclk) begin
        if (!aresetn) begin
            response_target <= 0;
            local_response <= 0;
            local_error <= 0;
            local_data <= 0;
            model_base <= 0;
        end else begin
            if (rsp_ready)
                local_response <= 0;
            if (cmd_valid && cmd_ready) begin
                response_target <= select_ffn ? 2'd1 : select_encoder ? 2'd2 : 2'd0;
                local_response <= !select_ffn && !select_encoder;
                local_error <= !(select_model_id || select_features || (select_model && cmd_read) || model_write);
                local_data <= select_model_id ? 32'h4d4f4431 :
                    select_features ? {31'd0, (FAST_FFN_ROWS!=0 && FAST_HANDOFF!=0)} : model_base;
            end
            if (model_write)
                model_base <= cmd_wdata;
        end
    end

    z100_axi_mmio control(
        .aclk(aclk), .aresetn(aresetn),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb), .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready), .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready), .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready), .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready),
        .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_read(cmd_read),
        .cmd_addr(cmd_addr), .cmd_wdata(cmd_wdata), .cmd_wmask(cmd_wmask),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_data(rsp_data), .rsp_error(rsp_error)
    );

    generate if (FAST_FFN_ROWS != 0) begin: parallel_ffn
    z100_ffn_rows #(.STREAM(FAST_HANDOFF),.GELU_CYCLES(GELU_CYCLES)) ffn(
        .clk(aclk), .rst_n(aresetn), .cmd_valid(cmd_valid && select_ffn),
        .cmd_ready(f_cmd_ready), .cmd_addr(cmd_addr[11:0]), .cmd_read(cmd_read),
        .cmd_wdata(cmd_wdata), .cmd_wmask(cmd_wmask), .rsp_valid(f_rsp_valid),
        .rsp_ready(rsp_ready && response_target == 1), .rsp_rdata(f_rsp_data), .rsp_err(f_rsp_error),
        .m_valid(f_valid), .m_ready(f_ready), .m_addr(f_addr), .m_wdata(f_data),
        .m_read(f_read), .m_rsp_valid(f_ddr_valid), .m_rdata(f_ddr_data), .m_err(f_error),
        .preload_permit(preload_permit), .input_valid(input_valid), .input_ready(input_ready), .input_data(input_data),
        .result_valid(result_valid), .result_ready(result_ready), .result_data(result_data), .link_error(link_error)
    );
    end else begin: serial_ffn
    assign input_ready=1'b0;
    assign result_valid=1'b0;
    assign result_data=40'd0;
    assign link_error=1'b0;
    z100_ffn ffn(
        .clk(aclk), .rst_n(aresetn), .cmd_valid(cmd_valid && select_ffn),
        .cmd_ready(f_cmd_ready), .cmd_addr(cmd_addr[11:0]), .cmd_read(cmd_read),
        .cmd_wdata(cmd_wdata), .cmd_wmask(cmd_wmask), .rsp_valid(f_rsp_valid),
        .rsp_ready(rsp_ready && response_target == 1), .rsp_rdata(f_rsp_data), .rsp_err(f_rsp_error),
        .m_valid(f_valid), .m_ready(f_ready), .m_addr(f_addr), .m_wdata(f_data),
        .m_read(f_read), .m_rsp_valid(f_ddr_valid), .m_rdata(f_ddr_data), .m_err(f_error)
    );
    end endgenerate

    kwt_encoder #(.PROJECTION_K4(FAST_PROJECTION), .ATTENTION_K16(FAST_ATTENTION),
        .STREAM_ENABLE(FAST_FFN_ROWS!=0 && FAST_HANDOFF!=0)) encoder(
        .clk(aclk), .rst_n(aresetn), .cmd_valid(cmd_valid && select_encoder),
        .cmd_ready(e_cmd_ready), .cmd_addr({8'b0, cmd_addr[11:0]}), .cmd_read(cmd_read),
        .cmd_wdata(cmd_wdata), .cmd_wmask(cmd_wmask), .rsp_valid(e_rsp_valid),
        .rsp_ready(rsp_ready && response_target == 2), .rsp_rdata(e_rsp_data), .rsp_err(e_rsp_error),
        .m_valid(e_valid), .m_ready(e_ready), .m_addr(e_addr), .m_wdata(e_data),
        .m_read(e_read), .m_mask(e_mask), .m_rsp_valid(e_ddr_valid), .m_rsp_ready(e_ddr_ready),
        .m_rdata(e_ddr_data), .m_err(e_error), .result_valid(result_valid), .result_ready(result_ready), .result_data(result_data),
        .preload_permit(preload_permit), .input_valid(input_valid), .input_ready(input_ready), .input_data(input_data),
        .link_abort_in(link_error), .link_abort_out()
    );

    kwt_dma_arbiter arbiter(
        .clk(aclk), .rst_n(aresetn),
        .f_valid(f_valid), .f_ready(f_ready), .f_addr(f_addr), .f_wdata(f_data), .f_read(f_read),
        .f_mask(4'hf), .f_rsp_valid(f_ddr_valid), .f_rsp_ready(1'b1), .f_rdata(f_ddr_data), .f_err(f_error),
        .e_valid(e_valid), .e_ready(e_ready), .e_addr(e_addr), .e_wdata(e_data), .e_read(e_read),
        .e_mask(e_mask), .e_rsp_valid(e_ddr_valid), .e_rsp_ready(e_ddr_ready), .e_rdata(e_ddr_data), .e_err(e_error),
        .d_valid(d_valid), .d_ready(d_ready), .d_addr(d_addr), .d_wdata(d_data), .d_read(d_read),
        .d_mask(d_mask), .d_rsp_valid(d_rsp_valid), .d_rsp_ready(d_rsp_ready),
        .d_rdata(d_rsp_data), .d_err(d_error)
    );

    z100_axi_ddr #(.LINE_WORDS(FAST_HANDOFF!=0 ? 64 : 16),.REFILL(FAST_HANDOFF)) memory(
        .aclk(aclk), .aresetn(aresetn), .req_valid(d_valid), .req_ready(d_ready),
        .model_base(model_base), .invalidate(model_write),
        .req_addr(d_addr), .req_data(d_data), .req_read(d_read), .req_mask(d_mask),
        .rsp_valid(d_rsp_valid), .rsp_ready(d_rsp_ready), .rsp_data(d_rsp_data), .rsp_error(d_error),
        .m_axi_awaddr(m_axi_awaddr), .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_awlen(m_axi_awlen), .m_axi_awsize(m_axi_awsize), .m_axi_awburst(m_axi_awburst),
        .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(m_axi_wstrb), .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready), .m_axi_bresp(m_axi_bresp), .m_axi_bvalid(m_axi_bvalid),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_bready(m_axi_bready), .m_axi_araddr(m_axi_araddr), .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready), .m_axi_rdata(m_axi_rdata), .m_axi_rresp(m_axi_rresp),
        .m_axi_arlen(m_axi_arlen), .m_axi_arsize(m_axi_arsize), .m_axi_arburst(m_axi_arburst),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid), .m_axi_rready(m_axi_rready)
    );
endmodule
