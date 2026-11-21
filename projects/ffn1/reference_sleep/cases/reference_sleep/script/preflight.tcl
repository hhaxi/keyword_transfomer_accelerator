# Optional: tclsh script/preflight.tcl (file/config checks, no DC license needed).
set backend_root [file normalize [file join [file dirname [info script]] ..]]
if {[catch {
    source [file join $backend_root script common.tcl]
    source [file join $backend_root config library_config.tcl]
    resolve_and_validate
} message]} { puts stderr $message; exit 1 }
puts "KWT_CONFIG_PASS: files exist and required settings are explicit."
puts "DB contents, macro pins, operating conditions, units and timing still need DC."
