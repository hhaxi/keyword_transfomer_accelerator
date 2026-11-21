# 150 MHz functional clock; no multicycle or false-path exceptions.
create_clock -name core_clk -period 6.666667 [get_ports clk]
set_clock_uncertainty 0.100 [get_clocks core_clk]
set_clock_transition 0.050 [get_clocks core_clk]
# Provisional system integration budget; replace only from official platform constraints.
set_input_delay -clock core_clk -max 1.000 [get_ports {rst_n cmd_valid cmd_addr* cmd_read cmd_wdata* cmd_wmask* rsp_ready ffn_mode gelu_input_shift* gelu_output_shift* dma_mode dma_load_valid dma_load_addr* dma_load_data* dma_start dma_clear dma_out_ready}]
set_input_delay -clock core_clk -min 0.000 [get_ports {rst_n cmd_valid cmd_addr* cmd_read cmd_wdata* cmd_wmask* rsp_ready ffn_mode gelu_input_shift* gelu_output_shift* dma_mode dma_load_valid dma_load_addr* dma_load_data* dma_start dma_clear dma_out_ready}]
set_output_delay -clock core_clk -max 1.000 [get_ports {cmd_ready rsp_valid rsp_rdata* rsp_err dma_load_ready dma_out_valid dma_out_data* dma_done dma_fault perf_cycles* perf_mac_cycles* perf_fifo_wait* perf_second_mac* perf_gelu* perf_saturation* perf_gelu_overlap* perf_parameter_wait*}]
set_output_delay -clock core_clk -min 0.000 [get_ports {cmd_ready rsp_valid rsp_rdata* rsp_err dma_load_ready dma_out_valid dma_out_data* dma_done dma_fault perf_cycles* perf_mac_cycles* perf_fifo_wait* perf_second_mac* perf_gelu* perf_saturation* perf_gelu_overlap* perf_parameter_wait*}]
