# The row wrapper latches GELU input on edge N and enables the activation
# BRAM write on edge N+2 at the earliest. Shift registers hold for the layer.
set gelu_sources [get_cells -hier -filter {REF_NAME =~ FD* && (NAME =~ */gelu_input_reg* || NAME =~ */parallel_ffn.ffn/shift_in_reg* || NAME =~ */parallel_ffn.ffn/shift_out_reg*)}]
set gelu_ram [get_cells -hier -filter {REF_NAME =~ RAMB* && NAME =~ */ffn2/activation_banks*}]
set gelu_data [get_pins -of_objects $gelu_ram -filter {REF_PIN_NAME =~ DI*}]
set_multicycle_path 2 -setup -from $gelu_sources -to $gelu_data
set_multicycle_path 1 -hold -from $gelu_sources -to $gelu_data
