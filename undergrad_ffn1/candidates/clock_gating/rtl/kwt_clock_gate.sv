// Positive-edge clock gate. Enable is held constant throughout the high phase.
// Simulation/frontend synthesis uses the latch model. DC must use a real ICG.
module kwt_clock_gate(input wire clk,en,test_en,output wire gclk);
`ifdef KWT_USE_LIBRARY_ICG
 `include "kwt_icg_instance.vh"
`else
 reg enable_latched;
 always_latch if(!clk) enable_latched=en | test_en;
 assign gclk=clk & enable_latched;
`endif
endmodule
