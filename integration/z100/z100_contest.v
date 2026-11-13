// Board-side loader. The complete contest SoC only sees its native ICB host port.
module z100_contest (
    input wire aclk, aresetn,
    input wire [19:0] s_axi_awaddr,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,
    input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid,
    output wire s_axi_wready,
    output wire [1:0] s_axi_bresp,
    output wire s_axi_bvalid,
    input wire s_axi_bready,
    input wire [19:0] s_axi_araddr,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output wire [31:0] s_axi_rdata,
    output wire [1:0] s_axi_rresp,
    output wire s_axi_rvalid,
    input wire s_axi_rready,
    output wire [31:0] m_axi_araddr,
    output wire [7:0] m_axi_arlen,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_arburst,
    output wire m_axi_arvalid,
    input wire m_axi_arready,
    input wire [31:0] m_axi_rdata,
    input wire [1:0] m_axi_rresp,
    input wire m_axi_rlast,m_axi_rvalid,
    output wire m_axi_rready
);
    wire cmd_valid, cmd_ready, cmd_read;
    wire [19:0] cmd_addr;
    wire [31:0] cmd_data;
    wire [3:0] cmd_mask;
    wire rsp_ready, h_ready, h_rsp_valid, h_err;
    wire [31:0] h_rdata, pc;
    reg local_valid, local_error, boot_hold, soc_enable;
    reg [31:0] local_data;
    wire local_access=cmd_addr[19];
    wire control=cmd_addr==20'h80000;
    wire identity=cmd_addr==20'h80004 && cmd_read;
    wire inspect=cmd_addr==20'h80008 && cmd_read;
    wire source_select=cmd_addr==20'h80010;
    wire destination_select=cmd_addr==20'h80014;
    wire transfer=cmd_addr==20'h80018;
    reg [31:0] load_source;
    reg [18:0] load_destination;
    wire loader_busy, loader_fault, loader_valid;
    wire [18:0] loader_addr;
    wire write_ok=!cmd_read && cmd_mask==4'hf && !loader_busy;
    wire local_take=cmd_valid && cmd_ready && local_access;
    assign cmd_ready=local_access ? !local_valid : !loader_busy && h_ready;
    assign m_axi_arsize=3'd2;
    assign m_axi_arburst=2'b01;

    always @(posedge aclk) begin
        if(!aresetn) begin
            local_valid<=0;local_error<=0;local_data<=0;boot_hold<=1;soc_enable<=1;
            load_source<=0;load_destination<=0;
        end else begin
            if(local_valid && rsp_ready) local_valid<=0;
            if(local_take) begin
                local_valid<=1;
                local_error<=!(identity || inspect || (control && (cmd_read || write_ok)) ||
                    ((source_select || destination_select) && write_ok) || (transfer && (cmd_read || write_ok)));
                local_data<=identity ? 32'h4b575443 : inspect ? pc :
                    transfer ? {30'd0,loader_fault,loader_busy} : {30'd0,soc_enable,boot_hold};
                if(control && write_ok) begin
                    boot_hold<=cmd_data[0];soc_enable<=cmd_data[1];
                end
                if(source_select && write_ok) load_source<=cmd_data;
                if(destination_select && write_ok) load_destination<=cmd_data[18:0];
            end
        end
    end

    z100_axi_mmio #(.ADDR_WIDTH(20)) axi(
        .aclk(aclk),.aresetn(aresetn),.s_axi_awaddr(s_axi_awaddr),.s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),.s_axi_wdata(s_axi_wdata),.s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid),.s_axi_wready(s_axi_wready),.s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid),.s_axi_bready(s_axi_bready),.s_axi_araddr(s_axi_araddr),
        .s_axi_arvalid(s_axi_arvalid),.s_axi_arready(s_axi_arready),.s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp),.s_axi_rvalid(s_axi_rvalid),.s_axi_rready(s_axi_rready),
        .cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.cmd_addr(cmd_addr),.cmd_read(cmd_read),
        .cmd_wdata(cmd_data),.cmd_wmask(cmd_mask),.rsp_valid(local_valid || (h_rsp_valid && !loader_busy)),
        .rsp_ready(rsp_ready),.rsp_data(local_valid ? local_data : h_rdata),
        .rsp_error(local_valid ? local_error : h_err)
    );

    z100_contest_loader loader(
        .clk(aclk),.rst_n(aresetn),.start(local_take && transfer && write_ok),
        .source(load_source),.destination(load_destination),.words(cmd_data[15:0]),
        .busy(loader_busy),.fault(loader_fault),.araddr(m_axi_araddr),.arlen(m_axi_arlen),
        .arvalid(m_axi_arvalid),.arready(m_axi_arready),.rdata(m_axi_rdata),
        .rresp(m_axi_rresp),.rvalid(m_axi_rvalid),.rlast(m_axi_rlast),.rready(m_axi_rready),
        .host_valid(loader_valid),.host_ready(h_ready),.host_addr(loader_addr),
        .host_response(h_rsp_valid && loader_busy),.host_error(h_err)
    );

    kwt_encoder_soc #(.PROJECTION_K4(1),.WIDE_MACRO(1)) contest(
        .clk(aclk),.rst_n(aresetn && soc_enable),.boot_hold(boot_hold),
        .h_valid(loader_busy ? loader_valid : cmd_valid && !local_access),.h_ready(h_ready),
        .h_addr({13'h1400,loader_busy ? loader_addr : cmd_addr[18:0]}),
        .h_wdata(loader_busy ? m_axi_rdata : cmd_data),.h_read(!loader_busy && cmd_read),
        .h_mask(loader_busy ? 4'hf : cmd_mask),
        .h_rsp_valid(h_rsp_valid),.h_rsp_ready(loader_busy || (rsp_ready && !local_valid)),
        .h_rdata(h_rdata),.h_err(h_err),.inspect_pc(pc)
    );
endmodule
