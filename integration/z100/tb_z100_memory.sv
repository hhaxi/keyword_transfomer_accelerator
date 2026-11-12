`timescale 1ns/1ps
module tb_z100_memory #(parameter LINE_WORDS=16, parameter REFILL=0);
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg [31:0] model_base = 0;
    reg invalidate = 0, req_valid = 0, req_read = 0;
    reg rsp_ready = 1;
    reg [31:0] req_addr, req_data;
    reg [3:0] req_mask = 4'hf;
    wire req_ready, rsp_valid, rsp_error;
    wire [31:0] rsp_data, araddr;
    wire [7:0] arlen;
    wire arvalid, rready;
    reg [31:0] read_addr;
    reg [7:0] beats = 0;
    reg error_beat = 0;
    int transactions = 0;
    int before_scratch;
    reg [31:0] last_araddr;
    reg [7:0] last_arlen;
    wire arready = beats == 0;
    wire rvalid = beats != 0;

    z100_axi_ddr #(.LINE_WORDS(LINE_WORDS),.REFILL(REFILL)) dut(
        .aclk(clk), .aresetn(rst_n), .model_base(model_base), .invalidate(invalidate),
        .req_valid(req_valid), .req_ready(req_ready), .req_addr(req_addr), .req_data(req_data),
        .req_read(req_read), .req_mask(req_mask), .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
        .rsp_data(rsp_data), .rsp_error(rsp_error),
        .m_axi_awready(1'b0), .m_axi_wready(1'b0), .m_axi_bresp(2'b00), .m_axi_bvalid(1'b0),
        .m_axi_araddr(araddr), .m_axi_arlen(arlen), .m_axi_arvalid(arvalid), .m_axi_arready(arready),
        .m_axi_rdata(read_addr ^ 32'h5a5aa5a5), .m_axi_rresp(error_beat && beats == 7 ? 2'b10 : 2'b00),
        .m_axi_rlast(beats == 1), .m_axi_rvalid(rvalid), .m_axi_rready(rready)
    );

    always @(posedge clk) begin
        if (arvalid && arready) begin
            read_addr <= araddr;
            beats <= arlen + 1;
            transactions <= transactions + 1;
            last_araddr <= araddr;
            last_arlen <= arlen;
        end else if (rvalid && rready) begin
            beats <= beats - 1;
            read_addr <= read_addr + 4;
        end
    end

    task automatic access(input [31:0] addr, input bit read_op, input [31:0] data,
                          input [31:0] expect_data, input bit expect_error);
        @(negedge clk);
        req_addr = addr;
        req_read = read_op;
        req_data = data;
        req_valid = 1;
        do @(posedge clk); while (!req_ready);
        @(negedge clk);
        req_valid = 0;
        while (!rsp_valid) @(negedge clk);
        if (rsp_error !== expect_error || (read_op && !expect_error && rsp_data !== expect_data))
            $fatal(1, "access %08x result %08x error=%0b", addr, rsp_data, rsp_error);
    endtask

    task automatic model_read(input [31:0] virtual_addr, input [31:0] expected_addr);
        access(virtual_addr, 1, 0, expected_addr ^ 32'h5a5aa5a5, 0);
    endtask

    initial begin
        repeat (4) @(negedge clk);
        rst_n = 1;
        model_read(32'ha0050000, 32'h10050000);
        if (last_arlen != 0) $fatal(1, "legacy path burst");
        @(negedge clk);
        model_base = 32'h11000010;
        invalidate = 1;
        @(negedge clk);
        invalidate = 0;
        model_read(32'ha0050000, model_base);
        if (last_araddr !== 32'h11000000 || last_arlen != LINE_WORDS-1) $fatal(1, "model burst");
        model_read(32'ha0050004, model_base + 4);
        if (transactions != 2) $fatal(1, "cache hit issued AXI request");
        if (REFILL != 0) begin
            rsp_ready = 0;
            repeat (3) @(negedge clk);
            if (!rsp_valid || req_ready || rsp_data !== ((model_base+4) ^ 32'h5a5aa5a5))
                $fatal(1, "Cache reply changed under backpressure");
            req_valid = 1;
            req_addr = 32'ha0050008;
            rsp_ready = 1;
            @(posedge clk);
            if (!req_ready || !rsp_valid) $fatal(1, "Cache could not retire and refill on the same edge");
            @(negedge clk);
            req_valid = 0;
            if (!rsp_valid || rsp_error || rsp_data !== ((model_base+8) ^ 32'h5a5aa5a5))
                $fatal(1, "Cache refill data mismatch");
        end
        model_read(32'ha00604fc, model_base + 66812);
        model_read(32'ha0020000, model_base + 66816);
        model_read(32'ha0028000, model_base + 99584);
        model_read(32'ha0040000, model_base + 100608);
        model_read(32'ha00480fc, model_base + 133628);
        before_scratch = transactions;
        access(32'ha0018000, 0, 32'h01234567, 0, 0);
        access(32'ha003c5fc, 0, 32'h89abcdef, 0, 0);
        access(32'ha0018000, 1, 0, 32'h01234567, 0);
        access(32'ha003c5fc, 1, 0, 32'h89abcdef, 0);
        if (transactions != before_scratch) $fatal(1, "scratch accessed DDR");
        @(negedge clk);
        error_beat = 1;
        access(32'ha0050000, 1, 0, 0, 1);
        @(negedge clk);
        error_beat = 0;
        model_read(32'ha0050000, model_base);
        if (transactions != before_scratch + 2) $fatal(1, "erroneous burst remained cached");
        $display("Z100_MEMORY_PASS");
        $finish;
    end
    initial #20000 $fatal(1, "memory test timeout");
endmodule
