# 150 MHz initial interface budget. Replace I/O delays and load with platform values.
create_clock -name clk -period 6.666667 [get_ports clk]
set_clock_uncertainty 0.100 [get_clocks clk]
set_clock_transition 0.050 [get_clocks clk]
set inputs [remove_from_collection [all_inputs] [get_ports clk]]
set_input_delay -clock clk -max 1.000 $inputs
set_input_delay -clock clk -min 0.000 $inputs
set_input_transition 0.100 $inputs
set_output_delay -clock clk -max 1.000 [all_outputs]
set_output_delay -clock clk -min 0.000 [all_outputs]
set_load 0.020 [all_outputs]
