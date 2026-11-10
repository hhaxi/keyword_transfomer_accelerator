# Analysis only: original DDC/libraries/constraints; no compilation or overrides.
set sh_continue_on_error false
if {[catch {
    if {![info exists env(KWT_DIAGNOSTIC_INPUTS)]} { error "set KWT_DIAGNOSTIC_INPUTS to the prepared inputs.tcl" }
    source $env(KWT_DIAGNOSTIC_INPUTS)
    cd $diagnostic_dir
    foreach path [concat [list $saved_ddc] $diagnostic_libraries] {
        if {![file isfile $path]} { error "saved input missing: $path" }
    }
    set_app_var target_library [list $diagnostic_target_library]
    set_app_var link_library [concat [list *] $diagnostic_libraries]
    foreach db $diagnostic_libraries { read_db $db }
    # Tracking starts here, but historical RTL renaming cannot be reconstructed.
    if {$saved_saif_kind eq "rtl" && [llength [info commands saif_map]]} { saif_map -start }
    read_ddc $saved_ddc
    current_design $saved_top
    if {![link]} { error "saved DDC failed to link with its original library list" }
    if {[sizeof_collection [get_clocks -quiet *]]==0} {
        if {![file isfile $saved_sdc]} { error "DDC has no clocks and original SDC is missing" }
        read_sdc $saved_sdc
    }
    if {[sizeof_collection [get_clocks -quiet *]]==0} { error "saved design has no clocks" }
    source [file join $diagnostic_dir power_diagnostics.tcl]
    kwt_diag::structure [file join $diagnostic_dir mapped]
    set annotation_valid 1
    if {$saved_saif ne ""} {
        if {![file isfile $saved_saif]} { error "saved SAIF missing: $saved_saif" }
        reset_switching_activity
        set options [list -input $saved_saif -instance_name $saved_instance -verbose]
        if {$saved_saif_kind eq "rtl"} { set options [linsert $options 0 -auto_map_names] }
        if {[catch {
            redirect -file annotation.rpt { set annotated [read_saif {*}$options] }
        } message]} {
            puts stderr "KWT_DIAGNOSTIC_ANNOTATION_FAILED: $message"
            set annotation_valid 0
        } elseif {![string is boolean -strict $annotated] || !$annotated} {
            puts stderr "KWT_DIAGNOSTIC_ANNOTATION_FAILED: read_saif returned '$annotated'"
            set annotation_valid 0
        }
    } else {
        set out [open NO_SAIF_VECTORLESS_ONLY.txt w]
        puts $out "No SAIF provided. Activity/power is vectorless and cannot qualify task power."
        close $out
    }
    kwt_diag::activity [file join $diagnostic_dir annotated_before_power] before_power 0
    kwt_diag::activity [file join $diagnostic_dir annotated_after_power] after_power 1
    if {!$annotation_valid} { error "SAIF annotation failed; partial diagnostics retained" }
    set out [open diagnostics_complete.ok w]
    puts $out "Analysis completed; original RTL annotation equivalence, clock coverage and power accuracy NOT certified."
    close $out
} message]} {
    puts stderr "KWT_POWER_DIAGNOSTICS_FAILED: $message"
    if {[info exists errorInfo]} { puts stderr $errorInfo }
    exit 1
}
puts "KWT_POWER_DIAGNOSTICS_COMPLETED: $diagnostic_dir"
exit 0