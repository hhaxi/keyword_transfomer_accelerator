// Same E203/host/shared-SRAM fabric, with an additional encoder register window
// at 0x40080000 and a fair arbiter for the two hardware DMA masters.
module kwt_extended_system_bus(
    input wire clk,rst_n,
    input wire c_valid,output wire c_ready,input wire [31:0] c_addr,c_wdata,
    input wire c_read,input wire [3:0] c_mask,
    output wire c_rsp_valid,input wire c_rsp_ready,output wire [31:0] c_rdata,output wire c_err,
    input wire h_valid,output wire h_ready,input wire [31:0] h_addr,h_wdata,
    input wire h_read,input wire [3:0] h_mask,
    output wire h_rsp_valid,input wire h_rsp_ready,output wire [31:0] h_rdata,output wire h_err
);
    wire d_valid,d_ready,d_read,d_rsp_valid,d_rsp_ready,d_err;
    wire [31:0] d_addr,d_wdata,d_rdata;wire [3:0] d_mask;
    wire a_valid,a_ready,a_read,a_rsp_valid,a_rsp_ready,a_err;
    wire [19:0] a_addr;wire [31:0] a_wdata,a_rdata;wire [3:0] a_mask;
    wire ram_cs,ram_we;wire [16:0] ram_addr;wire [3:0] ram_mask;wire [31:0] ram_wdata,ram_rdata;
    wire f_valid,f_ready,f_read,f_rsp_valid,f_rsp_ready,f_err;
    wire [31:0] f_addr,f_wdata,f_rdata;wire [3:0] f_mask;
    wire e_valid,e_ready,e_read,e_rsp_valid,e_rsp_ready,e_err;
    wire [31:0] e_addr,e_wdata,e_rdata;wire [3:0] e_mask;
    wire fa_ready,ea_ready,fa_rsp_valid,ea_rsp_valid,fa_err,ea_err;
    wire [31:0] fa_rdata,ea_rdata;reg register_owner;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) register_owner<=0;
        else if(a_valid && a_ready) register_owner<=a_addr[19];
    end
    assign a_ready=a_addr[19] ? ea_ready : fa_ready;
    assign a_rsp_valid=register_owner ? ea_rsp_valid : fa_rsp_valid;
    assign a_rdata=register_owner ? ea_rdata : fa_rdata;
    assign a_err=register_owner ? ea_err : fa_err;
    kwt_bus_fabric fabric(.*);
    kwt_dma_arbiter dma_arbiter(.*);
    kwt_shared_sram shared(.clk(clk),.cs(ram_cs),.we(ram_we),.addr(ram_addr),.mask(ram_mask),.din(ram_wdata),.dout(ram_rdata));
    kwt_dma accelerator(.clk(clk),.rst_n(rst_n),.cmd_valid(a_valid && !a_addr[19]),.cmd_ready(fa_ready),
        .cmd_addr(a_addr),.cmd_read(a_read),.cmd_wdata(a_wdata),.cmd_wmask(a_mask),
        .rsp_valid(fa_rsp_valid),.rsp_ready(a_rsp_ready && !register_owner),.rsp_rdata(fa_rdata),.rsp_err(fa_err),
        .m_valid(f_valid),.m_ready(f_ready),.m_addr(f_addr),.m_wdata(f_wdata),.m_read(f_read),.m_mask(f_mask),
        .m_rsp_valid(f_rsp_valid),.m_rsp_ready(f_rsp_ready),.m_rdata(f_rdata),.m_err(f_err));
    kwt_encoder encoder(.clk(clk),.rst_n(rst_n),.cmd_valid(a_valid && a_addr[19]),.cmd_ready(ea_ready),
        .cmd_addr({1'b0,a_addr[18:0]}),.cmd_read(a_read),.cmd_wdata(a_wdata),.cmd_wmask(a_mask),
        .rsp_valid(ea_rsp_valid),.rsp_ready(a_rsp_ready && register_owner),.rsp_rdata(ea_rdata),.rsp_err(ea_err),
        .m_valid(e_valid),.m_ready(e_ready),.m_addr(e_addr),.m_wdata(e_wdata),.m_read(e_read),.m_mask(e_mask),
        .m_rsp_valid(e_rsp_valid),.m_rsp_ready(e_rsp_ready),.m_rdata(e_rdata),.m_err(e_err));
endmodule
