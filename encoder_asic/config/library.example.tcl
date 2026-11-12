# Copy to local.tcl, or set KWT_DC_STDLIB and KWT_DC_SRAM_DBS.
# Do not add proprietary libraries to git.
set std_db /path/to/scc40nll_vhsc40_rvt_ss_v0p99_125c_basic.db
set sram_dbs [list /path/to/RAMSP128X16.db /path/to/RAMSP1024X16.db /path/to/RAMSP4096X16.db]
# Optional real workload activity. Without this, no activity-based power report is emitted.
# set saif_file /path/to/encoder.saif
# set saif_instance tb_encoder_dc/dut
