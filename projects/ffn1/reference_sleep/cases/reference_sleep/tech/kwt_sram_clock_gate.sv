// Local SRAM clock gate: the enable follows cs only during clock low.
// No reset or extra SRAM data register. The high pulse cannot be cut short
// or created by an enable transition while clk is high. Library mapping and
// physical clock-gating checks must be confirmed on the synthesis server.
module kwt_sram_clock_gate(
    input wire clk,enable,
    output wire gated_clk
);
    reg enable_latched;
    always_latch
        if(!clk) enable_latched=enable;
    assign gated_clk=clk & enable_latched;
endmodule
