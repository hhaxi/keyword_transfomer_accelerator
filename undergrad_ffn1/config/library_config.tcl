# -----------------------------------------------------------------------------
# KWT / SMIC40 RVT SS library and platform configuration.
# User-editable settings ONLY. No account-specific absolute home directory.
# -----------------------------------------------------------------------------
if {[info exists env(HOME)]} {
    set desktop_dir [file join $env(HOME) Desktop]
} elseif {[info exists env(USERPROFILE)]} {
    set desktop_dir [file join $env(USERPROFILE) Desktop]
} else { error "HOME (server) or USERPROFILE (Windows checks) is required" }
set std_root [file join $desktop_dir lib S40 S40 smic SCC40NLL_VHSC40_RVT_V0.1]
set std_basename scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db
# Leave empty to search std_root recursively for exactly std_basename.
set std_db ""

# Native single-port SRAMs in the user's Desktop library copy.
set sram_root [file join $desktop_dir lib SRAM_Lib_2025]
set sram_corner ss_0p99v_0p99v_125c
# Existing DBs only. Convert Liberty manually before starting DC.
# Empty per-macro DB paths are derived AFTER local overrides are sourced.
set sram_db_128 ""
set sram_db_1024 ""
set sram_db_4096 ""

# SP controls: EMA is 3 bits; EMAW is 2 bits. Zero is the initial configuration;
# check against the SP macro documentation before physical signoff.
set sram_ema 0
set sram_emaw 0
set sram_controls_confirmed 1

# Optional foundry-specific operating-condition name. Empty uses each loaded
# SS library's default. Inspect generated report_lib files to confirm P/V/T.
set std_operating_condition ""
set max_cores 8
set synthesis_scope soc
set use_designware 0
set dma_burst 1
set host_burst 0
set opt_itcm 0
set opt_host_continuous 0
set opt_small_x 0
set opt_small_bias 0
if {[file isfile [file join $backend_root config optimization_config.tcl]]} {
    source [file join $backend_root config optimization_config.tcl]
}

# Timing values use ns and pF. These are explicit initial interface budgets,
# not measurements of the external CPU/shared SRAM. Replace with platform data.
set clock_period_ns 6.666667
set clock_uncertainty_ns 0.100
# Legacy clock_uncertainty_ns remains a fallback for old local configurations.
# Empty setup/hold fields inherit it; set each explicitly for platform budgets.
set clock_setup_uncertainty_ns ""
set clock_hold_uncertainty_ns ""
set clock_transition_ns 0.050
set input_transition_ns 0.100
set io_input_max_ns 1.000
set io_input_min_ns 0.000
set io_output_max_ns 1.000
set io_output_min_ns 0.000
set output_load_pf 0.020

# Shared synchronous SRAM: request is launched on a rising edge; read data is
# captured on the following edge. Budget clock-to-Q plus external connection.
set shared_read_max_ns 1.000
set shared_read_min_ns 0.000
set shared_setup_ns 1.000
set shared_hold_ns 0.000

# Optional, fully specified platform wire-load model. Do not invent a model.
set wire_load_model ""
set wire_load_library ""

# Optional private override (ignored by git). Useful on the server.
set local_config [file join $backend_root config local_config.tcl]
if {[file isfile $local_config]} { source $local_config }
if {[info exists env(KWT_GLOBAL_LOCAL_CONFIG)] && [file isfile $env(KWT_GLOBAL_LOCAL_CONFIG)]} {
    source $env(KWT_GLOBAL_LOCAL_CONFIG)
}
if {[info exists env(KWT_SYNTHESIS_SCOPE)]} { set synthesis_scope $env(KWT_SYNTHESIS_SCOPE) }
if {$clock_setup_uncertainty_ns eq ""} { set clock_setup_uncertainty_ns $clock_uncertainty_ns }
if {$clock_hold_uncertainty_ns eq ""} { set clock_hold_uncertainty_ns $clock_uncertainty_ns }

foreach words {128 1024 4096} {
    set macro RAMSP${words}X16
    set basename ${macro}_${sram_corner}
    if {[set sram_db_$words] eq ""} {
        set sram_db_$words [file join $sram_root $macro db ${basename}.db]
    }
}
