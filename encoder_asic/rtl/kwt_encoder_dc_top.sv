// Accelerator-only ASIC boundary. CPU/shared SRAM remain outside this top.
// MMIO: FFN 0x4000_0000, encoder 0x4001_0000. One configuration response outstanding.
module kwt_encoder_dc_top #(
 parameter [31:0] FFN_BASE=32'h40000000, ENC_BASE=32'h40010000
)(
 input wire clk,rst_n,
 input wire c_valid,output wire c_ready,input wire [31:0] c_addr,c_wdata,
 input wire c_read,input wire [3:0] c_mask,
 output wire c_rsp_valid,input wire c_rsp_ready,output wire [31:0] c_rdata,output wire c_err,
 output wire m_valid,input wire m_ready,output wire [31:0] m_addr,m_wdata,
 output wire m_read,output wire [3:0] m_mask,
 input wire m_rsp_valid,output wire m_rsp_ready,input wire [31:0] m_rdata,input wire m_err
);
 wire sel_f=c_addr[31:12]==FFN_BASE[31:12],sel_e=c_addr[31:12]==ENC_BASE[31:12];
 wire f_cmd_ready,e_cmd_ready,f_rsp_valid,e_rsp_valid,f_rsp_err,e_rsp_err;
 wire [31:0] f_rsp_data,e_rsp_data;
 reg pending;reg [1:0] owner;
 wire free_cmd=!pending;
 assign c_ready=free_cmd && (sel_f ? f_cmd_ready : sel_e ? e_cmd_ready : 1'b1);
 assign c_rsp_valid=pending && (owner==0 ? f_rsp_valid : owner==1 ? e_rsp_valid : 1'b1);
 assign c_rdata=owner==0 ? f_rsp_data : owner==1 ? e_rsp_data : 32'd0;
 assign c_err=owner==0 ? f_rsp_err : owner==1 ? e_rsp_err : 1'b1;
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n) begin pending<=0;owner<=2;end
  else begin
   if(c_rsp_valid && c_rsp_ready) pending<=0;
   if(c_valid && c_ready) begin pending<=1;owner<=sel_f ? 0 : sel_e ? 1 : 2;end
  end
 end
 wire f_valid,f_ready,f_read,f_rsp,f_error,e_valid,e_ready,e_read,e_rsp,e_response_ready,e_error;
 wire [31:0] f_addr,f_data,f_rdata,e_addr,e_data,e_rdata;
 wire [3:0] e_mask;
 wire preload_permit,input_valid,input_ready,result_valid,result_ready,link_error;
 wire [31:0] input_data;wire [39:0] result_data;
 kwt_ffn_rows_parallel #(.STREAM(1),.GELU_CYCLES(2)) ffn(
  .clk(clk),.rst_n(rst_n),.cmd_valid(c_valid && free_cmd && sel_f),.cmd_ready(f_cmd_ready),
  .cmd_addr(c_addr[11:0]),.cmd_read(c_read),.cmd_wdata(c_wdata),.cmd_wmask(c_mask),
  .rsp_valid(f_rsp_valid),.rsp_ready(pending && owner==0 && c_rsp_ready),
  .rsp_rdata(f_rsp_data),.rsp_err(f_rsp_err),
  .m_valid(f_valid),.m_ready(f_ready),.m_addr(f_addr),.m_wdata(f_data),.m_read(f_read),
  .m_rsp_valid(f_rsp),.m_rdata(f_rdata),.m_err(f_error),
  .preload_permit(preload_permit),.input_valid(input_valid),.input_ready(input_ready),.input_data(input_data),
  .result_valid(result_valid),.result_ready(result_ready),.result_data(result_data),.link_error(link_error));
 kwt_encoder #(.PROJECTION_K4(2),.ATTENTION_K16(2),.STREAM_ENABLE(1)) encoder(
  .clk(clk),.rst_n(rst_n),.cmd_valid(c_valid && free_cmd && sel_e),.cmd_ready(e_cmd_ready),
  .cmd_addr({8'd0,c_addr[11:0]}),.cmd_read(c_read),.cmd_wdata(c_wdata),.cmd_wmask(c_mask),
  .rsp_valid(e_rsp_valid),.rsp_ready(pending && owner==1 && c_rsp_ready),
  .rsp_rdata(e_rsp_data),.rsp_err(e_rsp_err),
  .m_valid(e_valid),.m_ready(e_ready),.m_addr(e_addr),.m_wdata(e_data),.m_read(e_read),.m_mask(e_mask),
  .m_rsp_valid(e_rsp),.m_rsp_ready(e_response_ready),.m_rdata(e_rdata),.m_err(e_error),
  .result_valid(result_valid),.result_ready(result_ready),.result_data(result_data),
  .preload_permit(preload_permit),.input_valid(input_valid),.input_ready(input_ready),.input_data(input_data),
  .link_abort_in(link_error),.link_abort_out());
 kwt_dma_arbiter arbiter(
  .clk(clk),.rst_n(rst_n),.f_valid(f_valid),.f_ready(f_ready),.f_addr(f_addr),.f_wdata(f_data),
  .f_read(f_read),.f_mask(4'hf),.f_rsp_valid(f_rsp),.f_rsp_ready(1'b1),.f_rdata(f_rdata),.f_err(f_error),
  .e_valid(e_valid),.e_ready(e_ready),.e_addr(e_addr),.e_wdata(e_data),.e_read(e_read),.e_mask(e_mask),
  .e_rsp_valid(e_rsp),.e_rsp_ready(e_response_ready),.e_rdata(e_rdata),.e_err(e_error),
  .d_valid(m_valid),.d_ready(m_ready),.d_addr(m_addr),.d_wdata(m_wdata),.d_read(m_read),.d_mask(m_mask),
  .d_rsp_valid(m_rsp_valid),.d_rsp_ready(m_rsp_ready),.d_rdata(m_rdata),.d_err(m_err));
endmodule
