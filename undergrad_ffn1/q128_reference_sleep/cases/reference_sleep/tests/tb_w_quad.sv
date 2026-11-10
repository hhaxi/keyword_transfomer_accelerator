`timescale 1ns/1ps
`ifndef CORE
`define CORE dut
`endif
module tb_w_quad;
  reg clk=0,rst_n=0;
  always #5 clk=~clk;
  reg dma_load_valid=0,dma_w_valid=0,dma_start=0,dma_clear=0;
  reg [19:0] dma_load_addr=0;
  reg [31:0] dma_load_data=0;
  reg [63:0] dma_w_quad=0;
  reg [11:0] dma_w_index=0;
  wire dma_load_ready,dma_w_ready,dma_out_valid,dma_done,dma_fault;
  wire [1:0] dma_x_free;
  wire [63:0] dma_out_data;
  wire [14:0] dma_out_index;
  wire [31:0] perf_cycles,perf_mac_cycles,perf_fifo_wait;
  kwt_tile_core #(.FUSE(1),.SMALL_BIAS(1)) dut(
    .clk(clk),.rst_n(rst_n),.dma_load_valid(dma_load_valid),
    .dma_load_addr(dma_load_addr),.dma_load_data(dma_load_data),
    .dma_load_ready(dma_load_ready),.dma_w_valid(dma_w_valid),
    .dma_w_quad(dma_w_quad),.dma_w_index(dma_w_index),.dma_w_ready(dma_w_ready),
    .dma_x_valid(1'b0),.dma_x_residual(68'b0),.dma_x_index(11'b0),.dma_x_ready(),
    .dma_start(dma_start),.dma_clear(dma_clear),.dma_x_free(dma_x_free),
    .dma_out_valid(dma_out_valid),.dma_out_data(dma_out_data),
    .dma_out_index(dma_out_index),.dma_out_ready(1'b0),
    .dma_done(dma_done),.dma_fault(dma_fault),.perf_cycles(perf_cycles),
    .perf_mac_cycles(perf_mac_cycles),.perf_fifo_wait(perf_fifo_wait));
  reg [63:0] expected [0:4095];
  reg [4095:0] input_file,test_name;
  reg verify_mapping=0,scan_memory=0,forbid_writes=0;
  integer q,bank_writes=0,scan_count=0;
  genvar c,p;
  generate for(c=0;c<8;c=c+1)begin:columns
    for(p=0;p<2;p=p+1)begin:parities
      integer a,ref_q;
      always @(posedge clk) begin
        if(forbid_writes && `CORE.columns[c].parity[p].wm.we !== 0)
          $fatal(1,"W write during reset/clear/busy/bad index bank=%0d/%0d",c,p);
        if(verify_mapping) begin
          if(`CORE.columns[c].parity[p].wm.we !== ((c/2)==dma_w_index[6:5]))
            $fatal(1,"quad=%0d wrong bank write col=%0d parity=%0d",dma_w_index,c,p);
          if(`CORE.columns[c].parity[p].wm.we) begin
            bank_writes=bank_writes+1;
            if(`CORE.read_operands || !`CORE.columns[c].parity[p].wm.cs)
              $fatal(1,"W bank read/write conflict");
            if(`CORE.columns[c].parity[p].wm.addr !== {dma_w_index[11:7],dma_w_index[4:0]} ||
               `CORE.columns[c].parity[p].wm.din !== dma_w_quad[(c%2)*32+p*16+:16])
              $fatal(1,"quad=%0d wrong bank address/data col=%0d parity=%0d",dma_w_index,c,p);
          end
        end
      end
      always @(posedge scan_memory) begin
        for(a=0;a<1024;a=a+1) begin
          ref_q=((a>>5)<<7)|((c/2)<<5)|(a&31);
          if(`CORE.columns[c].parity[p].wm.native1024.u_macro.model.mem[a] !==
             expected[ref_q][(c%2)*32+p*16+:16])
            $fatal(1,"SRAM contents col=%0d parity=%0d addr=%0d quad=%0d",c,p,a,ref_q);
          scan_count=scan_count+1;
        end
      end
    end
  end endgenerate

  task reset_core(input bit use_clear);
    begin
      @(negedge clk); dma_w_valid=0; dma_load_valid=0; dma_start=0;
      if(use_clear) dma_clear=1; else rst_n=0;
      forbid_writes=1;
      repeat(2) @(negedge clk);
      if(`CORE.nw !== 0 || dma_fault || `CORE.complete_load || dma_w_ready)
        $fatal(1,"reset/clear retained W validity");
      dma_clear=0; rst_n=1; forbid_writes=0;
    end
  endtask
  task send_quad(input integer index);
    begin
      @(negedge clk); dma_w_valid=1; dma_w_index=index; dma_w_quad=expected[index];
      verify_mapping=1;
      @(posedge clk);
      if(!dma_w_ready) $fatal(1,"quad unexpectedly blocked index=%0d",index);
      #1;
      if(dma_fault || `CORE.nw !== index+1) $fatal(1,"W accepted count index=%0d",index);
      @(negedge clk); verify_mapping=0; dma_w_valid=0;
    end
  endtask
  task load_xb(input [19:0] addr);
    begin
      @(negedge clk); dma_load_valid=1; dma_load_addr=addr;
      @(posedge clk); if(!dma_load_ready) $fatal(1,"X/B unexpectedly blocked");
      #1; if(dma_fault) $fatal(1,"X/B load fault");
      @(negedge clk); dma_load_valid=0;
    end
  endtask
  initial begin
    if(!$value$plusargs("INPUT=%s",input_file)) $fatal(1,"INPUT missing");
    if(!$value$plusargs("NAME=%s",test_name)) test_name="unknown";
    $readmemh(input_file,expected);
    reset_core(0);
    // A skipped sequence number must fault without writing any bank.
    @(negedge clk); dma_w_valid=1; dma_w_index=1; forbid_writes=1;
    @(posedge clk); #1;
    if(!dma_fault || `CORE.nw !== 0) $fatal(1,"bad index accepted");
    reset_core(1);
    for(q=0;q<13;q=q+1) send_quad(q);
    reset_core(0);
    // Prepare one X tile and all biases using the original load port.
    for(q=0;q<256;q=q+1) load_xb(20'h10000+q*8);
    for(q=0;q<256;q=q+1) load_xb(20'h30000+q*4);
    for(q=0;q<4096;q=q+1) begin
      if(`CORE.complete_load) $fatal(1,"W marked complete before quad4095");
      send_quad(q);
    end
    if(!`CORE.complete_load || dma_w_ready || `CORE.nw !== 4096)
      $fatal(1,"4096 quads did not complete W load");
    scan_memory=1; #1; scan_memory=0;
    if(scan_count!=16384 || bank_writes!=(4096+13)*4)
      $fatal(1,"mapping coverage writes=%0d scan=%0d",bank_writes,scan_count);
    @(negedge clk); dma_start=1;
    @(posedge clk); #1;
    if(dma_fault || !`CORE.busy) $fatal(1,"complete W load did not start");
    @(negedge clk); dma_start=0; dma_w_valid=1; dma_w_index=0; forbid_writes=1;
    repeat(4) begin
      @(posedge clk); #1;
      if(dma_w_ready || `CORE.nw !== 4096) $fatal(1,"W accepted while busy");
    end
    reset_core(1);
    // The address-driven load port is now X/B only.
    @(negedge clk); dma_load_valid=1; dma_load_addr=20'h20000;
    @(posedge clk); #1;
    if(!dma_fault || `CORE.nw !== 0) $fatal(1,"legacy W address accepted");
    reset_core(1);
    send_quad(0);
    // Clear an incomplete load while an otherwise valid quad is offered.
    @(negedge clk); dma_clear=1; dma_w_valid=1; dma_w_index=1; forbid_writes=1;
    @(posedge clk); #1;
    if(`CORE.nw !== 0 || dma_w_ready || `CORE.complete_load)
      $fatal(1,"clear accepted W quad");
    $display("W_QUAD_PASS name=%0s quads=4096 banks=16 checked_halfwords=%0d bad_index=1 restart=2 busy=1",test_name,scan_count);
    $finish;
  end
endmodule
