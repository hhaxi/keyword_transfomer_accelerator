// Ordered DMA bridge. A nonzero model_base selects packed weights in DDR and
// keeps the two inter-engine buffers in PL BRAM. DMA addresses stay unchanged.
module z100_axi_ddr #(parameter LINE_WORDS=16, parameter REFILL=0) (
    input wire aclk, aresetn,
    input wire [31:0] model_base,
    input wire invalidate,
    input wire req_valid,
    output wire req_ready,
    input wire [31:0] req_addr, req_data,
    input wire req_read,
    input wire [3:0] req_mask,
    output wire rsp_valid,
    input wire rsp_ready,
    output reg [31:0] rsp_data,
    output reg rsp_error,
    output reg [31:0] m_axi_awaddr,
    output wire [7:0] m_axi_awlen,
    output wire [2:0] m_axi_awsize,
    output wire [1:0] m_axi_awburst,
    output reg m_axi_awvalid,
    input wire m_axi_awready,
    output reg [31:0] m_axi_wdata,
    output reg [3:0] m_axi_wstrb,
    output wire m_axi_wlast,
    output reg m_axi_wvalid,
    input wire m_axi_wready,
    input wire [1:0] m_axi_bresp,
    input wire m_axi_bvalid,
    output wire m_axi_bready,
    output reg [31:0] m_axi_araddr,
    output reg [7:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output reg m_axi_arvalid,
    input wire m_axi_arready,
    input wire [31:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast,
    input wire m_axi_rvalid,
    output wire m_axi_rready
);
    localparam IDLE = 3'd0, READ = 3'd1, WRITE = 3'd2, REPLY = 3'd3, LOCAL_REPLY = 3'd4;
    localparam LINE_BITS=$clog2(LINE_WORDS);
    reg [2:0] state;
    wire fast = model_base != 0;
    wire window_ok = req_addr[31:19] == 13'h1400 && req_addr[1:0] == 0;
    wire [18:0] offset = req_addr[18:0];
    wire handoff_input = offset >= 19'h18000 && offset < 19'h1b180;
    wire handoff_output = offset >= 19'h30000 && offset < 19'h3c600;
    wire local_access = fast && (handoff_input || handoff_output);
    wire [13:0] scratch_index = handoff_input ? {2'b00, offset[13:2]} : offset[15:2] + 14'd3168;
    (* ram_style = "block" *) reg [31:0] scratch [0:15839];
    reg [31:0] scratch_data;
    reg [31:0] payload;
    integer byte_lane;
    always @(posedge aclk) if (req_valid && req_ready && window_ok && local_access) begin
        if (req_read) scratch_data <= scratch[scratch_index];
        else for (byte_lane = 0; byte_lane < 4; byte_lane = byte_lane + 1)
            if (req_mask[byte_lane])
                scratch[scratch_index][8*byte_lane+:8] <= req_data[8*byte_lane+:8];
    end
    always @* rsp_data = state == LOCAL_REPLY ? scratch_data : payload;

    reg model_word;
    reg [17:0] model_offset;
    always @* begin
        model_word = 1;
        if (offset >= 19'h50000 && offset < 19'h60500)
            model_offset = {2'b0, offset[15:0]} + (offset[16] ? 18'd0 : 18'd65536);
        else if (offset >= 19'h20000 && offset < 19'h28400)
            model_offset = 18'd66816 + {2'b0, offset[15:0]};
        else if (offset >= 19'h40000 && offset < 19'h48100)
            model_offset = 18'd100608 + {2'b0, offset[15:0]};
        else begin
            model_word = 0;
            model_offset = 0;
        end
    end
    wire [31:0] physical_addr = fast && model_word ? model_base + {14'd0, model_offset} :
        {13'h0200, offset};
    reg line_valid, filling;
    reg [29-LINE_BITS:0] line_tag;
    reg [LINE_BITS-1:0] requested_word, fill_index;
    reg [31:0] line [0:LINE_WORDS-1];
    wire [29-LINE_BITS:0] address_tag = physical_addr[31:LINE_BITS+2];
    wire [LINE_BITS-1:0] address_word = physical_addr[LINE_BITS+1:2];
    wire line_end = &fill_index;
    assign req_ready = state == IDLE || (REFILL!=0 && rsp_valid && rsp_ready);
    assign rsp_valid = state == REPLY || state == LOCAL_REPLY;
    assign m_axi_awlen = 0;
    assign m_axi_awsize = 3'd2;
    assign m_axi_awburst = 2'b01;
    assign m_axi_wlast = 1;
    assign m_axi_arsize = 3'd2;
    assign m_axi_arburst = 2'b01;
    assign m_axi_bready = state == WRITE;
    assign m_axi_rready = state == READ;

    always @(posedge aclk) begin
        if (!aresetn) begin
            state <= IDLE;
            m_axi_awvalid <= 0;
            m_axi_wvalid <= 0;
            m_axi_arvalid <= 0;
            line_valid <= 0;
            filling <= 0;
        end else begin
            if (m_axi_awvalid && m_axi_awready) m_axi_awvalid <= 0;
            if (m_axi_wvalid && m_axi_wready) m_axi_wvalid <= 0;
            if (m_axi_arvalid && m_axi_arready) m_axi_arvalid <= 0;
            case (state)
                IDLE, REPLY, LOCAL_REPLY: if (req_valid && req_ready) begin
                    rsp_error <= 0;
                    if (!window_ok || (fast && model_word && !req_read)) begin
                        payload <= 0;
                        rsp_error <= 1;
                        state <= REPLY;
                    end else if (local_access) begin
                        payload <= 0;
                        state <= req_read ? LOCAL_REPLY : REPLY;
                    end else if (req_read) begin
                        if (fast && line_valid && !invalidate && line_tag == address_tag) begin
                            payload <= line[address_word];
                            state <= REPLY;
                        end else begin
                            m_axi_araddr <= fast ? {address_tag, {(LINE_BITS+2){1'b0}}} : physical_addr;
                            m_axi_arlen <= fast ? 8'(LINE_WORDS-1) : 8'd0;
                            m_axi_arvalid <= 1;
                            line_valid <= 0;
                            filling <= fast;
                            line_tag <= address_tag;
                            requested_word <= address_word;
                            fill_index <= 0;
                            state <= READ;
                        end
                    end else begin
                        m_axi_awaddr <= {13'h0200, req_addr[18:0]};
                        m_axi_wdata <= req_data;
                        m_axi_wstrb <= req_mask;
                        m_axi_awvalid <= 1;
                        m_axi_wvalid <= 1;
                        if (line_tag == address_tag)
                            line_valid <= 0;
                        state <= WRITE;
                    end
                end else if (rsp_valid && rsp_ready) state <= IDLE;
                READ: if (m_axi_rvalid) begin
                    if (!filling || fill_index == requested_word)
                        payload <= m_axi_rdata;
                    if (filling)
                        line[fill_index] <= m_axi_rdata;
                    fill_index <= fill_index + 1'b1;
                    rsp_error <= rsp_error || (|m_axi_rresp) ||
                        (m_axi_rlast != (!filling || line_end));
                    if (m_axi_rlast) begin
                        line_valid <= filling && line_end && !rsp_error && m_axi_rresp == 0;
                        state <= REPLY;
                    end
                end
                WRITE: if (m_axi_bvalid) begin
                    payload <= 0;
                    rsp_error <= |m_axi_bresp;
                    state <= REPLY;
                end
            endcase
            if (invalidate) line_valid <= 0;
        end
    end
endmodule
