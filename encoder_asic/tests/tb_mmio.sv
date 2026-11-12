`timescale 1ns/1ps
module tb_mmio;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,c_valid=0,c_read=1,c_rsp_ready=1;
 reg [31:0] c_addr=0,c_wdata=0;reg [3:0] c_mask=15;
 wire c_ready,c_rsp_valid,c_err;wire [31:0] c_rdata,m_addr,m_wdata;
 wire m_valid,m_read,m_rsp_ready;wire [3:0] m_mask;
 kwt_encoder_dc_top dut(.clk(clk),.rst_n(rst_n),.c_valid(c_valid),.c_ready(c_ready),
 .c_addr(c_addr),.c_wdata(c_wdata),.c_read(c_read),.c_mask(c_mask),
 .c_rsp_valid(c_rsp_valid),.c_rsp_ready(c_rsp_ready),.c_rdata(c_rdata),.c_err(c_err),
 .m_valid(m_valid),.m_ready(1'b0),.m_addr(m_addr),.m_wdata(m_wdata),.m_read(m_read),.m_mask(m_mask),
 .m_rsp_valid(1'b0),.m_rsp_ready(m_rsp_ready),.m_rdata(32'd0),.m_err(1'b0));
 task access(input [31:0] address,input bit read_,input [31:0] data,input bit error_,input bit check_,input [31:0] expected);
  reg [31:0] held;reg held_error;
  begin
   @(negedge clk);c_addr=address;c_read=read_;c_wdata=data;c_valid=1;c_rsp_ready=0;
   do @(posedge clk);while(!c_ready);
   @(negedge clk);c_valid=0;
   while(!c_rsp_valid) @(negedge clk);
   held=c_rdata;held_error=c_err;
   if(c_err!==error_) $fatal(1,"MMIO error flag %h",address);
   if(check_ && c_rdata!==expected) $fatal(1,"MMIO readback %h got %h expected %h",address,c_rdata,expected);
   repeat(3) begin
    @(negedge clk);
    if(!c_rsp_valid || c_rdata!==held || c_err!==held_error || c_ready)
      $fatal(1,"MMIO response changed under backpressure");
   end
   c_rsp_ready=1;@(negedge clk);
  end
 endtask
 initial begin
  repeat(4) @(negedge clk);rst_n=1;
  access(32'h4000000c,1,0,0,1,32'h46464e5a);
  access(32'h40000004,1,0,0,1,0);
  access(32'h40010004,1,0,0,1,0);
  access(32'h50000000,1,0,1,0,0);
  access(32'h40000002,1,0,1,0,0);
  access(32'h4000003c,0,32'h0808,0,0,0);
  access(32'h40010020,0,32'ha0010000,0,0,0);
  if(m_valid) $fatal(1,"DMA issued before task start");
  $display("ASIC_MMIO_PASS IDs, decode, programming, unmapped/misaligned requests and response backpressure");$finish;
 end
 initial begin #100000;$fatal(1,"MMIO timeout");end
endmodule
