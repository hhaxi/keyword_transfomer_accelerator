# 150 MHz target; explicit interface budgets, in library time/load units (ns/pF).
create_clock -name core_clk -period 6.666667 [get_ports clk]
set_clock_uncertainty -setup 0.10 [get_clocks core_clk]
set_clock_uncertainty -hold 0.05 [get_clocks core_clk]
set_clock_transition 0.10 [get_clocks core_clk]
set_input_delay -max 0.40 -clock core_clk [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_input_delay -min 0.05 -clock core_clk [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_output_delay -max 0.40 -clock core_clk [all_outputs]
set_output_delay -min 0.05 -clock core_clk [all_outputs]
set_load 0.02 [all_outputs]
# Asynchronous external reset only; no arithmetic/data path exceptions.
set_false_path -from [get_ports rst_n]
