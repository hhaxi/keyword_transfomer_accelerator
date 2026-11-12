`timescale 1ns/1ps
module tb_z100_ffn;
    reg clk = 0;
    always #20 clk = ~clk;
    reg rst_n = 0;
    reg cmd_valid = 0, cmd_read = 0;
    reg [11:0] cmd_addr;
    reg [31:0] cmd_wdata;
    wire cmd_ready, rsp_valid, rsp_err;
    wire [31:0] rsp_rdata, m_addr, m_wdata;
    wire m_valid, m_read;
    reg m_rsp_valid = 0;
    reg m_err = 0, inject_error = 0;
    reg [31:0] m_rdata;
    reg [31:0] mem [0:131071];
    reg [63:0] expected [0:6335];
    reg [39:0] expected_ffn1 [0:25343];
    reg [15:0] expected_gelu [0:25343];
    bit compare_trace = 0;
    integer trace_index = 0;
    reg [31:0] config_words [0:1];
    reg [2:0] clock_count = 0;
    wire m_ready = clock_count != 3;
`ifdef Z100_TEST_FFN_STREAM
    wire input_ready, result_valid, link_error;
    wire [39:0] result_data;
    int input_count, result_count;
    bit test_input, test_output;
    wire result_ready = test_output && clock_count != 3;
    wire input_valid = test_input && input_count < 3168;
    wire [31:0] input_data = mem['h6000+input_count];
    z100_ffn_rows #(.STREAM(1),.GELU_CYCLES(2)) dut(
`elsif Z100_TEST_FFN_ROWS
    z100_ffn_rows dut(
`else
    z100_ffn dut(
`endif
        .clk(clk), .rst_n(rst_n), .cmd_valid(cmd_valid), .cmd_ready(cmd_ready),
        .cmd_addr(cmd_addr), .cmd_read(cmd_read), .cmd_wdata(cmd_wdata), .cmd_wmask(4'hf),
        .rsp_valid(rsp_valid), .rsp_ready(1'b1), .rsp_rdata(rsp_rdata), .rsp_err(rsp_err),
        .m_valid(m_valid), .m_ready(m_ready), .m_addr(m_addr), .m_wdata(m_wdata), .m_read(m_read),
        .m_rsp_valid(m_rsp_valid), .m_rdata(m_rdata), .m_err(m_err)
`ifdef Z100_TEST_FFN_STREAM
        ,.preload_permit(clock_count!=5),.input_valid(input_valid),.input_ready(input_ready),.input_data(input_data)
        ,.result_valid(result_valid),.result_ready(result_ready),.result_data(result_data),.link_error(link_error)
`endif
    );
    always @(posedge clk) begin
`ifdef Z100_TEST_FFN_STREAM
        if (input_valid && input_ready) input_count <= input_count + 1;
        if (result_valid && result_ready) begin
            if (result_count >= 6336 || {{24{result_data[39]}},result_data} !== expected[result_count])
                $fatal(1, "Layer %0d streamed FFN output %0d actual %h expected %h",
                    layer, result_count, result_data, expected[result_count]);
            result_count <= result_count + 1;
        end
`endif
        clock_count <= clock_count + 1'b1;
        m_rsp_valid <= m_valid && m_ready;
        m_err <= m_valid && m_ready && inject_error;
        if (m_valid && m_ready) begin
            if (m_addr < 32'ha0010000 || m_addr >= 32'ha0080000 || m_addr[1:0] != 0)
                $fatal(1, "DDR address %08x", m_addr);
            if (m_read)
                m_rdata <= mem[m_addr[18:2]];
            else
                mem[m_addr[18:2]] <= m_wdata;
        end
`ifndef Z100_TEST_FFN_ROWS
        if (compare_trace && dut.l1_valid && dut.l2_input_ready) begin
            if (dut.l1_data[39:0] !== expected_ffn1[trace_index] ||
                dut.ffn2.gelu !== expected_gelu[trace_index])
                $fatal(1, "FFN1/GELU mismatch at input element %0d", trace_index);
            trace_index <= trace_index + 1;
        end
`endif
    end

    task automatic request(input bit read_flag, input [11:0] address,
                           input [31:0] data, output reg [31:0] result);
        @(negedge clk);
        cmd_read = read_flag;
        cmd_addr = address;
        cmd_wdata = data;
        cmd_valid = 1;
        do @(posedge clk); while (!cmd_ready);
        @(negedge clk);
        cmd_valid = 0;
        if (!rsp_valid || rsp_err)
            $fatal(1, "Invalid response for address %03x", address);
        result = rsp_rdata;
    endtask

    string root, layer_path, task_path;
    integer layers, layer, sample, trace_file;
    reg [31:0] result;
    initial begin
        if (!$value$plusargs("vectors=%s", root)) root = "vectors";
        if (!$value$plusargs("layers=%d", layers)) layers = 12;
        if (!$value$plusargs("sample=%d", sample)) sample = 0;
        repeat (4) @(negedge clk);
        rst_n = 1;
        inject_error = 1;
        request(0, 12'h000, 1, result);
        do request(1, 12'h004, 0, result); while (result[0]);
        if (result != 4)
            $fatal(1, "DDR fault did not drain: status %x", result);
        inject_error = 0;
        $display("Z100_FFN_DMA_FAULT_DRAIN_PASS");
        for (layer = 0; layer < layers; layer = layer + 1) begin
            layer_path = $sformatf("%s/layer_%02d", root, layer);
            task_path = $sformatf("%s/task_%02d/layer_%02d", root, sample, layer);
            $readmemh({layer_path, "/w1.hex"}, mem, 'h8000, 'h9fff);
            $readmemh({layer_path, "/b1.hex"}, mem, 'ha000, 'ha0ff);
            $readmemh({layer_path, "/w2.hex"}, mem, 'h10000, 'h11fff);
            $readmemh({layer_path, "/b2.hex"}, mem, 'h12000, 'h1203f);
            $readmemh({layer_path, "/config.hex"}, config_words);
            $readmemh({task_path, "/ffn_input.hex"}, mem, 'h6000, 'h6c5f);
            $readmemh({task_path, "/ffn.hex"}, expected);
`ifndef Z100_TEST_FFN_ROWS
            trace_file = $fopen({task_path, "/ffn1.hex"}, "r");
            compare_trace = trace_file != 0;
            trace_index = 0;
            if (compare_trace) begin
                $fclose(trace_file);
                $readmemh({task_path, "/ffn1.hex"}, expected_ffn1);
                $readmemh({task_path, "/gelu.hex"}, expected_gelu);
            end
`endif
            request(0, 12'h03c, config_words[0], result);
`ifdef Z100_TEST_FFN_STREAM
            test_input = 1;
            input_count = 0;
            result_count = 0;
`endif
`ifdef Z100_TEST_FFN_ROWS
            if (layer == 0) begin
                request(0, 12'h000, 1, result);
                wait (dut.state == dut.COMPUTE);
                repeat (50) @(negedge clk);
                request(0, 12'h000, 2, result);
                do request(1, 12'h004, 0, result); while (result[0]);
                if (result != 8)
                    $fatal(1, "FFN row lanes did not abort: status %x", result);
                $display("Z100_FFN_ROWS_ABORT_PASS");
`ifdef Z100_TEST_FFN_STREAM
                input_count = 0;
`endif
            end
`endif
            request(0, 12'h000, 1, result);
            do begin
                repeat (512) @(negedge clk);
                request(1, 12'h004, 0, result);
            end while (result[0]);
            if (result != 2)
                $fatal(1, "FFN fault at layer %0d status %x", layer, result);
            if (compare_trace && trace_index != 25344)
                $fatal(1, "Only compared %0d FFN1/GELU values", trace_index);
`ifdef Z100_TEST_FFN_STREAM
            test_output = 1;
            wait (result_count == 6336);
            repeat (4) @(negedge clk);
            if (result_valid || input_count != 3168 || link_error)
                $fatal(1, "Unexpected extra FFN data or error");
            test_output = 0;
`else
            for (int i = 0; i < 6336; i++)
                if ({mem['hc000+2*i+1], mem['hc000+2*i]} !== expected[i])
                    $fatal(1, "layer %0d output %0d actual %h expected %h", layer, i,
                        {mem['hc000+2*i+1], mem['hc000+2*i]}, expected[i]);
`endif
            request(1, 12'h040, 0, result);
            $display("Z100_FFN_PASS layer=%0d words=6336 trace=%0d cycles=%0d", layer, trace_index, result);
        end
        $finish;
    end
    initial begin
        #500000000;
        $fatal(1, "FFN simulation timeout");
    end
endmodule
