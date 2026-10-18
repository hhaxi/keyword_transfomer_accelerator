// E203, external loader and autonomous DMA share a pipelined round-robin bus.
module kwt_system_bus(
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
    wire ram_cs,ram_we;wire [16:0] ram_addr;wire [3:0] ram_mask;
    wire [31:0] ram_wdata,ram_rdata;
    kwt_bus_fabric fabric(.*);
    kwt_shared_sram shared(.clk(clk),.cs(ram_cs),.we(ram_we),.addr(ram_addr),
        .mask(ram_mask),.din(ram_wdata),.dout(ram_rdata));
    kwt_dma accelerator(.result_valid(),.result_ready(1'b0),.result_data(),.link_abort_in(1'b0),.link_abort_out(),.clk(clk),.rst_n(rst_n),.cmd_valid(a_valid),.cmd_ready(a_ready),
        .cmd_addr(a_addr),.cmd_read(a_read),.cmd_wdata(a_wdata),.cmd_wmask(a_mask),
        .rsp_valid(a_rsp_valid),.rsp_ready(a_rsp_ready),.rsp_rdata(a_rdata),.rsp_err(a_err),
        .m_valid(d_valid),.m_ready(d_ready),.m_addr(d_addr),.m_wdata(d_wdata),.m_read(d_read),.m_mask(d_mask),
        .m_rsp_valid(d_rsp_valid),.m_rsp_ready(d_rsp_ready),.m_rdata(d_rdata),.m_err(d_err));
endmodule
