// Simulation-only monitor. It runs outside the strict PPA measurement logic.
    wire [2:0] cov_cmd = {dut.bus.d_valid && dut.bus.d_ready,
                          h_valid && h_ready, dut.c_valid && dut.c_ready};
    wire [2:0] cov_rsp = {dut.bus.d_rsp_valid, h_rsp_valid, dut.c_rsp_valid};
    wire [2:0] cov_ready = {dut.bus.d_rsp_ready, h_rsp_ready, dut.c_rsp_ready};
    wire [2:0] cov_error = {dut.bus.d_err, h_err, dut.c_err};
    wire [2:0][31:0] cov_data = {dut.bus.d_rdata, h_rdata, dut.c_rdata};
    wire [1:0] cov_next_target = dut.bus.fabric.route_addr == 0 ? 2'd2 :
                                 dut.bus.fabric.route_addr[31] ? 2'd0 : 2'd1;
    bit cov_pending = 0;
    bit [2:0] cov_owner = 0, cov_stalled = 0;
    logic [1:0] cov_target;
    logic [2:0][32:0] cov_held;
    int unsigned cov_path[3][3][2];
    int unsigned cov_refills, cov_sram_to_reg, cov_reg_to_sram;
    int unsigned cov_stalls, cov_errors, cov_reset_pending;

    always @(posedge clk) begin
        if (!rst_n) begin
            if (cov_pending) cov_reset_pending++;
            cov_pending = 0;
            cov_stalled = 0;
        end else begin
            if (!$onehot0(cov_cmd) || !$onehot0(cov_rsp))
                $fatal(1, "KWT coverage: more than one bus command/response owner");
            if (cov_rsp != 0 && (!cov_pending || cov_rsp != cov_owner))
                $fatal(1, "KWT coverage: unsolicited response or wrong owner");
            for (int m = 0; m < 3; m++) begin
                if (cov_stalled[m] && (!cov_rsp[m] || {cov_error[m], cov_data[m]} !== cov_held[m]))
                    $fatal(1, "KWT coverage: response changed while stalled, master %0d", m);
                cov_stalled[m] = cov_rsp[m] && !cov_ready[m];
                cov_held[m] = {cov_error[m], cov_data[m]};
                if (cov_stalled[m]) cov_stalls++;
                if (cov_rsp[m] && cov_ready[m] && cov_error[m]) cov_errors++;
                if (cov_cmd[m]) cov_path[m][cov_next_target][dut.bus.fabric.read_ ? 0 : 1]++;
            end
            if (cov_pending && dut.bus.fabric.chosen_valid && (cov_rsp & cov_ready) != 0) begin
                if (cov_target == 0 && cov_next_target == 1 && cov_cmd == 0) cov_sram_to_reg++;
                if (cov_target == 1 && cov_next_target == 0 && cov_cmd == 0) cov_reg_to_sram++;
                if (cov_cmd != 0) cov_refills++;
            end
            if (cov_cmd != 0 && cov_pending && (cov_rsp & cov_ready) == 0)
                $fatal(1, "KWT coverage: accepted while an old response remained in flight");
            if ((cov_rsp & cov_ready) != 0) cov_pending = 0;
            if (cov_cmd != 0) begin
                cov_pending = 1;
                cov_owner = cov_cmd;
                cov_target = cov_next_target;
            end
        end
    end

    task automatic coverage_protocol;
        logic [31:0] probe_data;
        @(negedge clk); boot_hold = 1;
        repeat (8) @(negedge clk);
        host(0, 32'ha007fff0, 32'h12345678, probe_data);
        h_mask = 4'b0101;
        host(0, 32'ha007fff0, 32'haabbccdd, probe_data);
        h_mask = 4'hf;
        host(1, 32'ha007fff0, 0, probe_data);
        if (probe_data !== 32'h12bb56dd) $fatal(1, "KWT coverage: byte mask mismatch");

        @(negedge clk);
        h_addr = 32'h40000080; h_read = 1; h_valid = 1; h_rsp_ready = 0;
        do @(posedge clk); while (!h_ready);
        @(negedge clk); h_valid = 0;
        repeat (4) begin
            if (!h_rsp_valid || !h_err || h_rdata !== 0)
                $fatal(1, "KWT coverage: forbidden Host MMIO read must return a stable error");
            @(negedge clk);
        end
        h_rsp_ready = 1;
        @(negedge clk); h_rsp_ready = 0;

        h_addr = 32'ha007fff0; h_read = 1; h_valid = 1;
        do @(posedge clk); while (!h_ready);
        @(negedge clk); h_valid = 0;
        if (!h_rsp_valid || h_err) $fatal(1, "KWT coverage: missing response before reset");
        rst_n = 0;
        repeat (5) @(negedge clk);
        rst_n = 1;
        repeat (5) @(negedge clk);
        if (h_rsp_valid) $fatal(1, "KWT coverage: stale response after reset");
        host(1, 32'ha007fff0, 0, probe_data);
        if (probe_data !== 32'h12bb56dd) $fatal(1, "KWT coverage: read after reset failed");
        $display("KWT_COVERAGE_PROTOCOL_PASS");
    endtask

    task automatic coverage_report;
        string masters[3] = '{"cpu", "host", "dma"};
        string targets[3] = '{"sram", "register", "denied"};
        string operations[2] = '{"read", "write"};
        for (int m = 0; m < 3; m++)
            for (int t = 0; t < 3; t++)
                for (int op = 0; op < 2; op++)
                    $display("KWT_COV %s_%s_%s %0d", masters[m], targets[t],
                             operations[op], cov_path[m][t][op]);
        $display("KWT_COV same_cycle_refill %0d", cov_refills);
        $display("KWT_COV sram_to_register %0d", cov_sram_to_reg);
        $display("KWT_COV register_to_sram %0d", cov_reg_to_sram);
        $display("KWT_COV response_stall %0d", cov_stalls);
        $display("KWT_COV error_response %0d", cov_errors);
        $display("KWT_COV reset_with_pending %0d", cov_reset_pending);
    endtask
