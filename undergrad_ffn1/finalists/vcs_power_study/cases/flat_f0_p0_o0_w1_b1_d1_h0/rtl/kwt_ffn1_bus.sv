`include "kwt_optional.vh"
// E203, external loader and autonomous DMA share a pipelined round-robin bus.
module kwt_ffn1_bus #(parameter integer DMA_BURST=`KWT_DMA_BURST, HOST_BURST=`KWT_HOST_BURST)(
    input wire clk,rst_n,
    input wire c_valid,output wire c_ready,input wire [31:0] c_addr,c_wdata,
    input wire c_read,input wire [3:0] c_mask,
    output wire c_rsp_valid,input wire c_rsp_ready,output wire [31:0] c_rdata,output wire c_err,
    input wire h_valid,output wire h_ready,input wire [31:0] h_addr,h_wdata,
    input wire h_read,input wire [3:0] h_mask,
    output wire h_rsp_valid,input wire h_rsp_ready,output wire [31:0] h_rdata,output wire h_err,output wire cpu_irq
);
    wire d_valid,d_ready,d_read,d_rsp_valid,d_rsp_ready,d_err;
    wire [31:0] d_addr,d_wdata,d_rdata;wire [3:0] d_mask;
    wire a_valid,a_ready,a_read,a_rsp_valid,a_rsp_ready,a_err;
    wire [19:0] a_addr;wire [31:0] a_wdata,a_rdata;wire [3:0] a_mask;
    wire ram_cs,ram_we;wire [16:0] ram_addr;wire [3:0] ram_mask;
    wire [31:0] ram_wdata,ram_rdata;
    kwt_bus_fabric #(.DMA_BURST(DMA_BURST),.HOST_BURST(HOST_BURST)) fabric(.*);
    kwt_shared_sram shared(.clk(clk),.cs(ram_cs),.we(ram_we),.addr(ram_addr),
        .mask(ram_mask),.din(ram_wdata),.dout(ram_rdata));
    wire dma_event;
    wire dma_cmd_valid,dma_cmd_ready,dma_rsp_valid,dma_rsp_ready,dma_rsp_err;
    wire [31:0] dma_rsp_data;
    generate if(`KWT_IRQ) begin: interrupt_controller
        wire select_irq=a_addr[19:4]==16'h0008;
        wire irq_ready,irq_rsp_valid,irq_rsp_err;
        wire [31:0] irq_rsp_data;
        reg response_irq;
        always @(posedge clk or negedge rst_n)
            if(!rst_n) response_irq<=0;
            else if(a_valid && a_ready) response_irq<=select_irq;
        assign dma_cmd_valid=a_valid && !select_irq;
        assign a_ready=select_irq ? irq_ready : dma_cmd_ready;
        assign a_rsp_valid=response_irq ? irq_rsp_valid : dma_rsp_valid;
        assign a_rdata=response_irq ? irq_rsp_data : dma_rsp_data;
        assign a_err=response_irq ? irq_rsp_err : dma_rsp_err;
        assign dma_rsp_ready=a_rsp_ready && !response_irq;
        wire host_event=h_valid && h_ready && !h_read && h_addr==32'ha000f000 && h_mask==15 && (h_wdata==1 || h_wdata==3);
        kwt_event_irq events(.clk(clk),.rst_n(rst_n),.host_event(host_event),.dma_event(dma_event),.irq(cpu_irq),
            .cmd_valid(a_valid && select_irq),.cmd_ready(irq_ready),.cmd_addr(a_addr),.cmd_read(a_read),.cmd_wdata(a_wdata),.cmd_wmask(a_mask),
            .rsp_valid(irq_rsp_valid),.rsp_ready(a_rsp_ready && response_irq),.rsp_rdata(irq_rsp_data),.rsp_err(irq_rsp_err));
    end else begin: polling_only
        assign dma_cmd_valid=a_valid;assign a_ready=dma_cmd_ready;
        assign a_rsp_valid=dma_rsp_valid;assign a_rdata=dma_rsp_data;assign a_err=dma_rsp_err;
        assign dma_rsp_ready=a_rsp_ready;assign cpu_irq=0;
    end endgenerate
    kwt_ffn1_dma accelerator(.clk(clk),.rst_n(rst_n),.cmd_valid(dma_cmd_valid),.cmd_ready(dma_cmd_ready),
        .cmd_addr(a_addr),.cmd_read(a_read),.cmd_wdata(a_wdata),.cmd_wmask(a_mask),
        .rsp_valid(dma_rsp_valid),.rsp_ready(dma_rsp_ready),.rsp_rdata(dma_rsp_data),.rsp_err(dma_rsp_err),
        .m_valid(d_valid),.m_ready(d_ready),.m_addr(d_addr),.m_wdata(d_wdata),.m_read(d_read),.m_mask(d_mask),
        .m_rsp_valid(d_rsp_valid),.m_rsp_ready(d_rsp_ready),.m_rdata(d_rdata),.m_err(d_err),.irq_event(dma_event));
endmodule
