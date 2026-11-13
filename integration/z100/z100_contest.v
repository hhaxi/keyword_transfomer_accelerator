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
    input wire s_axi_rready
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
    assign cmd_ready=local_access ? !local_valid : h_ready;

    always @(posedge aclk) begin
        if(!aresetn) begin
            local_valid<=0;local_error<=0;local_data<=0;boot_hold<=1;soc_enable<=1;
        end else begin
            if(local_valid && rsp_ready) local_valid<=0;
            if(cmd_valid && cmd_ready && local_access) begin
                local_valid<=1;
                local_error<=!(identity || inspect || (control && (cmd_read || cmd_mask==4'hf)));
                local_data<=identity ? 32'h4b575443 : inspect ? pc : {30'd0,soc_enable,boot_hold};
                if(control && !cmd_read && cmd_mask==4'hf) begin
                    boot_hold<=cmd_data[0];soc_enable<=cmd_data[1];
                end
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
        .cmd_wdata(cmd_data),.cmd_wmask(cmd_mask),.rsp_valid(local_valid || h_rsp_valid),
        .rsp_ready(rsp_ready),.rsp_data(local_valid ? local_data : h_rdata),
        .rsp_error(local_valid ? local_error : h_err)
    );

    kwt_encoder_soc #(.PROJECTION_K4(1)) contest(
        .clk(aclk),.rst_n(aresetn && soc_enable),.boot_hold(boot_hold),
        .h_valid(cmd_valid && !local_access),.h_ready(h_ready),.h_addr({13'h1400,cmd_addr[18:0]}),
        .h_wdata(cmd_data),.h_read(cmd_read),.h_mask(cmd_mask),
        .h_rsp_valid(h_rsp_valid),.h_rsp_ready(rsp_ready && !local_valid),
        .h_rdata(h_rdata),.h_err(h_err),.inspect_pc(pc)
    );
endmodule
