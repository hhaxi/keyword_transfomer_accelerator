// DDR-backed FFN1 -> GELU -> FFN2. One in-order DDR transaction at a time.
module z100_ffn (
    input wire clk, rst_n,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [11:0] cmd_addr,
    input wire cmd_read,
    input wire [31:0] cmd_wdata,
    input wire [3:0] cmd_wmask,
    output reg rsp_valid,
    input wire rsp_ready,
    output reg [31:0] rsp_rdata,
    output reg rsp_err,
    output reg m_valid,
    input wire m_ready,
    output reg [31:0] m_addr, m_wdata,
    output reg m_read,
    input wire m_rsp_valid,
    input wire [31:0] m_rdata,
    input wire m_err
);
    localparam IDLE = 4'd0, CLEAR = 4'd1, W1 = 4'd2, B1 = 4'd3, W2 = 4'd4,
               B2 = 4'd5, FIRST_ROW = 4'd6, START = 4'd7, RUN = 4'd8, DRAIN = 4'd9;
    localparam [31:0] X_BASE = 32'ha0018000, W1_BASE = 32'ha0020000,
        B1_BASE = 32'ha0028000, Y_BASE = 32'ha0030000,
        W2_BASE = 32'ha0040000, B2_BASE = 32'ha0048000;
    reg [3:0] phase;
    reg [12:0] parameter_index, input_index, output_index;
    reg [4:0] gelu_input_shift, gelu_output_shift;
    reg [31:0] cycles;
    reg pending, write_high, done, fault, aborted;
    wire busy = phase != IDLE;
    wire bus_idle = !m_valid && !pending;
    wire retire = pending && m_rsp_valid;
    wire command = cmd_valid && cmd_ready;
    wire valid_write = command && !cmd_read && cmd_wmask == 4'hf && cmd_addr[1:0] == 0;
    wire abort_request = valid_write && cmd_addr == 0 && cmd_wdata == 2;
    wire [31:0] parameter_offset = {17'd0, parameter_index, 2'b0};
    wire [31:0] input_offset = {17'd0, input_index, 2'b0};
    wire [31:0] output_offset = {16'd0, output_index, write_high, 2'b0};
    wire [1:0] x_free;
    wire l1_ready, l1_valid, l1_done, l1_fault, l2_input_ready, l2_valid;
    wire [63:0] l1_data, l2_data;
    wire feed_x = phase == FIRST_ROW || phase == RUN;
    wire response_ok = retire && !m_err && !abort_request;
    wire l1_load = response_ok && m_read && (phase == W1 || phase == B1 || feed_x);
    wire [19:0] l1_addr = phase == W1 ? 20'h20000 + {4'd0, parameter_index, 3'd0} :
        phase == B1 ? 20'h30000 + {5'd0, parameter_index, 2'd0} :
        20'h10000 + {4'd0, input_index, 3'd0};
    wire l2_pop = phase == RUN && response_ok && !m_read && write_high;
    wire core_clear = phase == CLEAR || (phase == DRAIN && bus_idle);
    wire [31:0] ffn1_cycles;

    assign cmd_ready = !rsp_valid || rsp_ready;

    kwt_ffn1_core ffn1(
        .clk(clk), .rst_n(rst_n), .dma_load_valid(l1_load), .dma_load_addr(l1_addr),
        .dma_load_data(m_rdata), .dma_load_ready(l1_ready), .dma_start(phase == START),
        .dma_clear(core_clear), .dma_x_free(x_free), .dma_out_valid(l1_valid),
        .dma_out_data(l1_data), .dma_out_ready(l2_input_ready), .dma_done(l1_done),
        .dma_fault(l1_fault), .perf_cycles(ffn1_cycles), .perf_mac_cycles(), .perf_fifo_wait()
    );
    z100_ffn2 ffn2(
        .clk(clk), .rst_n(rst_n), .clear(core_clear),
        .weight_write(response_ok && phase == W2), .weight_index(parameter_index), .weight_data(m_rdata),
        .bias_write(response_ok && phase == B2), .bias_index(parameter_index[5:0]), .bias_data(m_rdata),
        .gelu_input_shift(gelu_input_shift), .gelu_output_shift(gelu_output_shift),
        .input_valid(l1_valid), .input_ready(l2_input_ready), .input_data(l1_data[39:0]),
        .output_valid(l2_valid), .output_ready(l2_pop), .output_data(l2_data)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase <= IDLE;
            parameter_index <= 0;
            input_index <= 0;
            output_index <= 0;
            gelu_input_shift <= 0;
            gelu_output_shift <= 0;
            cycles <= 0;
            pending <= 0;
            write_high <= 0;
            done <= 0;
            fault <= 0;
            aborted <= 0;
            m_valid <= 0;
            m_addr <= 0;
            m_wdata <= 0;
            m_read <= 0;
            rsp_valid <= 0;
            rsp_rdata <= 0;
            rsp_err <= 0;
        end else begin
            if (busy)
                cycles <= cycles + 1'b1;
            if (m_valid && m_ready) begin
                m_valid <= 0;
                pending <= 1;
            end
            if (retire)
                pending <= 0;

            if (bus_idle && !abort_request) begin
                case (phase)
                    W1, B1, W2, B2: begin
                        m_valid <= 1;
                        m_read <= 1;
                        case (phase)
                            W1: m_addr <= W1_BASE + parameter_offset;
                            B1: m_addr <= B1_BASE + parameter_offset;
                            W2: m_addr <= W2_BASE + parameter_offset;
                            default: m_addr <= B2_BASE + parameter_offset;
                        endcase
                    end
                    FIRST_ROW, RUN: begin
                        if (phase == RUN && l2_valid) begin
                            m_valid <= 1;
                            m_read <= 0;
                            m_addr <= Y_BASE + output_offset;
                            m_wdata <= write_high ? l2_data[63:32] : l2_data[31:0];
                        end else if (input_index < 3168 && x_free[input_index[5]]) begin
                            m_valid <= 1;
                            m_read <= 1;
                            m_addr <= X_BASE + input_offset;
                        end
                    end
                    default: begin end
                endcase
            end

            if (phase == CLEAR) begin
                parameter_index <= 0;
                input_index <= 0;
                output_index <= 0;
                write_high <= 0;
                phase <= W1;
            end
            if (phase == START)
                phase <= RUN;
            if (phase == DRAIN && bus_idle)
                phase <= IDLE;

            if (response_ok) begin
                case (phase)
                    W1, B1, W2, B2: begin
                        parameter_index <= parameter_index + 1'b1;
                        if (((phase == W1 || phase == W2) && parameter_index == 8191) ||
                            (phase == B1 && parameter_index == 255) ||
                            (phase == B2 && parameter_index == 63)) begin
                            parameter_index <= 0;
                            phase <= phase + 1'b1;
                        end
                    end
                    FIRST_ROW, RUN: begin
                        if (m_read) begin
                            input_index <= input_index + 1'b1;
                            if (phase == FIRST_ROW && input_index == 31)
                                phase <= START;
                        end else begin
                            write_high <= !write_high;
                            if (write_high) begin
                                output_index <= output_index + 1'b1;
                                if (output_index == 6335) begin
                                    phase <= IDLE;
                                    done <= l1_done;
                                    fault <= !l1_done;
                                end
                            end
                        end
                    end
                    default: begin end
                endcase
            end

            if (rsp_valid && rsp_ready)
                rsp_valid <= 0;
            if (command) begin
                rsp_valid <= 1;
                rsp_rdata <= 0;
                rsp_err <= 0;
                if (cmd_addr[1:0] != 0) rsp_err <= 1;
                else if (cmd_read) case (cmd_addr)
                    12'h004: rsp_rdata <= {28'd0, aborted, fault, done, busy};
                    12'h00c: rsp_rdata <= 32'h46464e5a;
                    12'h040: rsp_rdata <= cycles;
                    12'h044: rsp_rdata <= ffn1_cycles;
                    default: rsp_err <= 1;
                endcase
                else if (cmd_wmask != 4'hf) rsp_err <= 1;
                else case (cmd_addr)
                    12'h000: if (cmd_wdata == 1 && !busy) begin
                        phase <= CLEAR;
                        done <= 0;
                        fault <= 0;
                        aborted <= 0;
                        cycles <= 0;
                    end else if (cmd_wdata != 2) rsp_err <= 1;
                    12'h03c: if (!busy && (cmd_wdata & 32'hffffe0e0) == 0) begin
                        gelu_input_shift <= cmd_wdata[4:0];
                        gelu_output_shift <= cmd_wdata[12:8];
                    end else rsp_err <= 1;
                    default: rsp_err <= 1;
                endcase
            end
            if (busy && phase != DRAIN && (abort_request || (phase != CLEAR &&
                ((retire && m_err) || (l1_load && !l1_ready) || l1_fault)))) begin
                phase <= DRAIN;
                done <= 0;
                fault <= !abort_request;
                aborted <= abort_request;
            end
        end
    end
endmodule
