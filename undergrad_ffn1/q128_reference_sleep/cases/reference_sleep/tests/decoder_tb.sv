`timescale 1ns/1ps
module decoder_tb;
  reg clk = 0;
  always #5 clk = ~clk;
  reg rst_n = 0;
  reg clear = 0;
  reg in_valid = 0;
  wire in_ready;
  reg [31:0] in_word = 0;
  wire out_valid;
  reg out_ready = 0;
  wire [63:0] out_quad;
  wire [11:0] out_index;
  wire metadata_valid;
  wire [13:0] expected_words;
  wire done, fault;
  wire x_mode=1'b0;
  wire [3:0] x_query_tile=4'd0;
  wire [8:0] x_query_words;
  wire [67:0] out_residual;
  kwt_weight_unpack dut(.*);

  reg [31:0] stream [0:8223];
  reg [63:0] expected [0:4095];
  reg [4095:0] input_file, expected_file, test_name;
  integer word_count, seed, restarts, unused;
  reg [31:0] random_state;
  integer stalled_offers = 0;
  integer independent_offers = 0;
  integer input_stalls = 0;

  function [31:0] advance(input [31:0] state);
    advance = {state[30:0], state[31] ^ state[21] ^ state[1] ^ state[0]};
  endfunction

  task reset_decoder(input integer use_clear);
    begin
      @(negedge clk);
      in_valid = 0;
      out_ready = 0;
      if (use_clear) clear = 1; else rst_n = 0;
      repeat (2) @(negedge clk);
      if (out_valid !== 0 || metadata_valid !== 0 || done !== 0 || fault !== 0)
        $fatal(1, "reset/clear did not discard decoder state");
      clear = 0;
      rst_n = 1;
    end
  endtask

  task run_stream(input integer abort_words, input integer abort_pairs);
    integer sent, received, cycles, pending;
    reg was_stalled;
    reg [63:0] held_quad;
    reg [11:0] held_index;
    begin : transfer
      sent = 0;
      received = 0;
      cycles = 0;
      pending = 0;
      was_stalled = 0;
      while (cycles < 80000) begin
        @(negedge clk);
        random_state = advance(random_state);
        if (!pending && sent < word_count && random_state[2:0] != 0
            && (cycles < 128 || cycles % 509 >= 31)) pending = 1;
        in_valid = pending;
        in_word = sent < word_count ? stream[sent] : 32'hbad0feed;
        // Readiness depends on an existing offer. This catches ready->valid loops.
        out_ready = cycles >= 128 && out_valid && random_state[5:3] < 6
                    && (cycles % 997 >= 97);
        @(posedge clk);
        if (was_stalled && (out_valid !== 1 || out_quad !== held_quad || out_index !== held_index))
          $fatal(1, "output changed under stall at quad %0d", received);
        if (out_valid && !out_ready) begin
          stalled_offers = stalled_offers + 1;
          if (cycles < 128) independent_offers = independent_offers + 1;
        end
        was_stalled = out_valid && !out_ready;
        held_quad = out_quad;
        held_index = out_index;
        if (in_valid && !in_ready) input_stalls = input_stalls + 1;
        if (in_valid && in_ready) begin
          sent = sent + 1;
          pending = 0;
        end
        if (out_valid && out_ready) begin
          if (out_index !== received[11:0])
            $fatal(1, "index expected=%0d got=%0d", received, out_index);
          if (out_quad !== expected[received])
            $fatal(1, "quad=%0d expected=%016h got=%016h", received, expected[received], out_quad);
          received = received + 1;
        end
        cycles = cycles + 1;
        #1;
        if (fault !== 0) $fatal(1, "unexpected decoder fault");
        if (sent == word_count && in_ready !== 0) $fatal(1, "accepted beyond declared input size");
        if (metadata_valid !== (sent >= 32))
          $fatal(1, "metadata_valid sent=%0d got=%0b", sent, metadata_valid);
        if (metadata_valid && expected_words !== word_count[13:0])
          $fatal(1, "compressed size expected=%0d got=%0d", word_count, expected_words);
        if (done && received != 4096) $fatal(1, "premature done received=%0d", received);
        if ((abort_words > 0 && sent >= abort_words) || (abort_pairs > 0 && received >= abort_pairs))
          disable transfer;
        if (received == 4096) begin
          if (done !== 1 || sent != word_count || out_valid !== 0 || in_ready !== 0)
            $fatal(1, "completion mismatch sent=%0d expected=%0d done=%0b", sent, word_count, done);
          @(negedge clk);
          in_valid = 1;
          in_word = 32'hbad0feed;
          out_ready = 1;
          repeat (8) begin
            @(posedge clk);
            #1;
            if (!done || out_valid || in_ready || fault) $fatal(1, "completion not quiescent");
          end
          $display("DECODER_PASS name=%0s words=%0d quads=%0d cycles=%0d", test_name, sent, received, cycles);
          disable transfer;
        end
      end
      $fatal(1, "decoder timeout sent=%0d received=%0d", sent, received);
    end
  endtask

  initial begin
    if (!$value$plusargs("INPUT=%s", input_file)) $fatal(1, "INPUT missing");
    if (!$value$plusargs("EXPECTED=%s", expected_file)) $fatal(1, "EXPECTED missing");
    if (!$value$plusargs("COUNT=%d", word_count)) $fatal(1, "COUNT missing");
    if (!$value$plusargs("SEED=%d", seed)) seed = 32'h12345001;
    unused = $value$plusargs("NAME=%s", test_name);
    if (!$value$plusargs("RESTARTS=%d", restarts)) restarts = 0;
    random_state = seed;
    $readmemh(input_file, stream, 0, word_count-1);
    $readmemh(expected_file, expected);
    reset_decoder(0);
    if (restarts) begin
      run_stream(17, 0);
      reset_decoder(0);
      run_stream(36, 0);
      reset_decoder(1);
      run_stream(0, 4094);
      reset_decoder(0);
    end
    run_stream(0, 0);
    if (stalled_offers == 0 || independent_offers == 0 || input_stalls == 0)
      $fatal(1, "missing stalled output coverage");
    $display("DECODER_STALL_COVERAGE offers=%0d ready_independent=%0d input_stalls=%0d reset_cases=%0d", stalled_offers, independent_offers, input_stalls, restarts ? 3 : 0);
    $finish;
  end
endmodule




