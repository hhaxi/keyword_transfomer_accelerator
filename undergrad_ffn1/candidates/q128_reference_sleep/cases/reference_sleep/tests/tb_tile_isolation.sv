`timescale 1ns/1ps
module tb_tile_isolation;
    reg clk=0,rst_n=0;
    always #5 clk=~clk;
    wire dma_load_ready;
    wire [1:0] dma_x_free;
    wire dma_out_valid,dma_done,dma_fault;
    wire [63:0] dma_out_data;
    wire [14:0] dma_out_index;
    wire [31:0] perf_cycles,perf_mac_cycles,perf_fifo_wait;
    kwt_tile_core #(.FUSE(1),.SMALL_BIAS(1)) dut(
        .clk(clk),.rst_n(rst_n),.dma_load_valid(1'b0),.dma_load_addr(20'b0),
        .dma_load_data(32'b0),.dma_load_ready(dma_load_ready),
        .dma_w_valid(1'b0),.dma_w_quad(64'b0),.dma_w_index(12'b0),.dma_w_ready(),
        .dma_x_valid(1'b0),.dma_x_residual(68'b0),.dma_x_index(11'b0),.dma_x_ready(),
        .dma_start(1'b0),.dma_clear(1'b0),.dma_x_free(dma_x_free),
        .dma_out_valid(dma_out_valid),.dma_out_data(dma_out_data),
        .dma_out_index(dma_out_index),.dma_out_ready(1'b1),
        .dma_done(dma_done),.dma_fault(dma_fault),.perf_cycles(perf_cycles),
        .perf_mac_cycles(perf_mac_cycles),.perf_fifo_wait(perf_fifo_wait));
    integer errors=0;
    reg check_now=0;
    reg active=0;
    genvar r,c;
    generate for(r=0;r<8;r=r+1)begin:rows
        localparam [15:0] X0=16'h8000+r;
        localparam [15:0] X1=16'h7fff-r;
        // Deposit representative signed SRAM outputs to isolate datapath behavior
        // from memory loading; the separate SRAM bench tests all memory accesses.
        initial begin
            force dut.tiles[0].rows[r].parity[0].xm.native128.u_macro.model.Q=X0;
            force dut.tiles[0].rows[r].parity[1].xm.native128.u_macro.model.Q=X1;
        end
        for(c=0;c<8;c=c+1)begin:columns
            localparam [15:0] W0=16'hffef+c;
            localparam [15:0] W1=16'h0011+c;
            localparam signed [31:0] P0=$signed(X0)*$signed(W0);
            localparam signed [31:0] P1=$signed(X1)*$signed(W1);
            if(r==0) initial begin
                force dut.columns[c].parity[0].wm.native1024.u_macro.model.Q=W0;
                force dut.columns[c].parity[1].wm.native1024.u_macro.model.Q=W1;
            end
            always @(posedge check_now) begin
                if(dut.columns[c].pes[r].pe.p0 !== (active ? P0 : 32'sd0) ||
                   dut.columns[c].pes[r].pe.g_two.p1 !== (active ? P1 : 32'sd0)) begin
                    $display("TILE_ISOLATION_FAIL row=%0d col=%0d state=%0d active=%0d",r,c,dut.state,active);
                    errors=errors+1;
                end
            end
        end
    end endgenerate
    task check_products(input bit want_active);
        active=want_active; #1;
        if($test$plusargs("debug")) $display("ISOLATION_DEBUG state=%0d active=%b valid=%b fused=%b push=%b ready=%b",dut.state,active,dut.product_valid,dut.fused_seed,dut.push,dut.queue_ready);
        check_now=1; #1; check_now=0;
    endtask
    initial begin
        force dut.read_tile=0;
        #2; @(negedge clk); rst_n=1;
        force dut.state=0; check_products(0); // IDLE, including resident SRAM data
        force dut.state=3; check_products(0); // PRIME reads are not products
        force dut.state=4; check_products(1); // MAC
        force dut.state=5; check_products(1); // LAST consumes the final pair
        force dut.state=7;
        force dut.prefetched=1;
        force dut.x_valid=2'b11;
        force dut.row=0;
        force dut.col=0;
        check_products(1);                  // fused EMIT seeds the next group
        force dut.prefetched=0; check_products(0); // stalled/unfused EMIT
        force dut.state=8; check_products(0); // WAIT_TILE
        if(errors) $fatal(1,"TILE_ISOLATION errors=%0d",errors);
        $display("TILE_ISOLATION_PASS rows=8 columns=8 products=128 states=7");
        $finish;
    end
endmodule
