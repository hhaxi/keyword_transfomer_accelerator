# Read-only DC diagnostics. Optional/version-specific commands never hide failure.
# No compile, constraint setters, set_switching_activity, or ideal-network changes.
namespace eval kwt_diag {
    variable directory
    variable status
    variable unsupported
    array set unsupported {}
}
proc kwt_diag::clean {value} { return [string map [list \t { } \r { } \n { }] $value] }
proc kwt_diag::note {name state detail} {
    variable status
    puts $status "[clean $name]\t$state\t[clean $detail]"
    flush $status
}
proc kwt_diag::start {path phase} {
    variable directory
    variable status
    set directory $path
    file mkdir $directory
    if {[file exists [file join $directory availability.tsv]]} { error "diagnostics refuse overwrite: $directory" }
    set status [open [file join $directory availability.tsv] w]
    puts $status "report\tstatus\tdetail"
    set out [open [file join $directory READ_FIRST.txt] w]
    puts $out "Phase=$phase; diagnostic completion does not certify power or timing."
    puts $out "Seq SAIF coverage is distinct from gated-register coverage."
    puts $out "Handwritten latch+AND SRAM gates may be absent from report_clock_gating."
    puts $out "Inspect macro CLK/CEN raw activity sources and mapped upstream cones."
    puts $out "Input pin counts are mapped connection loads, not weighted Yosys bit loads."
    puts $out "Hierarchical net aliases can repeat the same electrical leaf endpoints. Do not sum net rows."
    puts $out "Unsupported/empty attributes are UNAVAILABLE, never invented or zero-filled."
    puts $out "No placed/routed RC; inspect original constraints, wire-load, ideal and high-fanout settings."
    close $out
}
proc kwt_diag::finish {} { variable status; close $status }
proc kwt_diag::report {name command} {
    variable directory
    set first [lindex $command 0]
    set result "command not installed: $first"
    set bad 1
    if {[llength [info commands $first]]} {
        set bad [catch {redirect -file [file join $directory $name] {uplevel #0 $command}} result]
    }
    if {$bad} {
        set out [open [file join $directory ${name}.unavailable.txt] w]
        puts $out "UNAVAILABLE: $result\ncommand=$command"
        close $out
        note $name UNAVAILABLE $result
        return 0
    }
    note $name COMPLETED_INSPECT_TEXT $command
    return 1
}
proc kwt_diag::attribute {object class name} {
    variable unsupported
    set key ${class}/${name}
    if {[info exists unsupported($key)]} { return $unsupported($key) }
    if {[catch {get_attribute $object $name} value]} {
        set value "UNAVAILABLE:[clean $value]"
        set unsupported($key) $value
        return $value
    }
    if {$value eq ""} { return "UNAVAILABLE:empty_or_undefined" }
    return [clean $value]
}
proc kwt_diag::introspection {} {
    foreach command {all_connected report_net report_power identify_clock_gating report_clock_gating report_saif report_activity get_switching_activity all_fanin} {
        report help_${command}.rpt [list help -verbose $command]
    }
    foreach class {design net pin port cell clock} {
        report attributes_${class}.rpt [list list_attributes -application -class $class]
    }
}
proc kwt_diag::settings {} {
    variable directory
    report design.rpt {report_design}
    report units.rpt {report_units}
    report clocks.rpt {report_clock}
    report constraints.rpt {report_constraint -all_violators -verbose}
    report ideal_networks.rpt {report_ideal_network}
    set out [open [file join $directory current_settings.tsv] w]
    puts $out "class\tobject\tsetting\tvalue"
    foreach name {target_library link_library high_fanout_net_threshold high_fanout_net_pin_capacitance power_default_toggle_rate power_default_static_probability} {
        if {[catch {get_app_var $name} value]} { set value "UNAVAILABLE:[clean $value]" }
        puts $out "app_var\tGLOBAL\t$name\t[clean $value]"
    }
    foreach name {wire_load_model wire_load_mode operating_conditions max_fanout} {
        puts $out "design\t[get_object_name [current_design]]\t$name\t[attribute [current_design] design $name]"
    }
    close $out
}
proc kwt_diag::gating {} {
    report identify_clock_gating.rpt {identify_clock_gating}
    report clock_gating.rpt {report_clock_gating}
    report clock_gating_elements.rpt {report_clock_gating -gating_elements}
    # Keep the installed tool's definition of covered registers/recognized gates.
    # Do not reinterpret SAIF Seq Cells coverage as clock-gating coverage.
}
proc kwt_diag::net_loads {} {
    variable directory
    set rows {}
    set header "net\tleaf_input_pin_loads\toutput_port_loads\tleaf_drivers\tunknown_endpoints\tcount_status\tfanout_attribute\tcapacitance\ttotal_capacitance\twire_capacitance\tpin_capacitance\tmax_fanout\tideal_network\tis_ideal"
    set all [open [file join $directory mapped_net_loads.tsv] w]
    puts $all $header
    foreach_in_collection net [get_nets -hierarchical -quiet *] {
        set name [get_object_name $net]
        set sinks 0; set outputs 0; set drivers 0; set unknown 0
        set mode leaf_endpoints
        if {![llength [info commands all_connected]] || [catch {all_connected -leaf $net} endpoints]} {
            set mode UNAVAILABLE_actual_leaf_connections
            set sinks -1; set outputs -1; set drivers -1; set unknown -1
        } else {
            foreach_in_collection endpoint $endpoints {
                set class [attribute $endpoint object object_class]
                set direction [attribute $endpoint $class direction]
                if {$class eq "pin" && $direction in {in input inout}} {
                    incr sinks
                } elseif {$class eq "port" && $direction in {out output inout}} {
                    incr outputs
                } elseif {($class eq "pin" && $direction in {out output}) || ($class eq "port" && $direction in {in input})} {
                    incr drivers
                } else { incr unknown }
            }
            if {$unknown} { set mode "LOWER_BOUND_unknown_endpoint_types" }
        }
        set values [list $name $sinks $outputs $drivers $unknown $mode]
        foreach attribute {fanout capacitance total_capacitance wire_capacitance pin_capacitance max_fanout ideal_network is_ideal} {
            lappend values [attribute $net net $attribute]
        }
        set line [join $values \t]
        puts $all $line
        lappend rows [list [expr {$sinks<0 ? -1 : $sinks+$outputs}] $name $net $line]
    }
    close $all
    set ranked [lsort -integer -decreasing -index 0 $rows]
    set high [open [file join $directory high_fanout_loads.tsv] w]
    puts $high $header
    set rank 0
    foreach row $ranked {
        lassign $row count name net line
        if {$count>=64 || [regexp -nocase {(^|/)(clk|clock|rst_n|reset|push|.*_push|.*enable.*|.*_cs)$} $name]} { puts $high $line }
        if {$rank<20} {
            report [format top_net_%02d.rpt $rank] [list report_net -connections -verbose $net]
            set endpoint_report [open [file join $directory [format top_net_%02d_endpoints.tsv $rank]] w]
            puts $endpoint_report "net=$name; rank=$rank; count=$count; inspect count_status in mapped_net_loads.tsv"
            if {[llength [info commands all_connected]] && ![catch {all_connected -leaf $net} endpoints]} {
                puts $endpoint_report "object\tclass\tdirection"
                foreach_in_collection endpoint $endpoints {
                    set class [attribute $endpoint object object_class]
                    puts $endpoint_report "[get_object_name $endpoint]\t$class\t[attribute $endpoint $class direction]"
                }
            } else { puts $endpoint_report "UNAVAILABLE actual leaf endpoints" }
            close $endpoint_report
        }
        incr rank
    }
    close $high
    note mapped_net_loads.tsv COMPLETED "nets=$rank; aliases may repeat leaf endpoints; capacitance follows report_units"
}
proc kwt_diag::macro_cones {} {
    variable directory
    set out [open [file join $directory macro_gate_inventory.tsv] w]
    puts $out "clock_report_index\tcell\tref_name\tis_integrated_clock_gating_cell\tis_clock_gating_cell\tis_hierarchical"
    set index 0
    foreach_in_collection cell [get_cells -hierarchical -quiet *] {
        set name [get_object_name $cell]
        set reference [attribute $cell cell ref_name]
        if {[string match RAMSP*X16 $reference] || [regexp -nocase {clock_gate|gated_clock|clk_gate|clkgate} $name]} {
            set clock_index NA
            if {[string match RAMSP*X16 $reference]} { set clock_index $index }
            set values [list $clock_index $name $reference]
            foreach attribute {is_integrated_clock_gating_cell is_clock_gating_cell is_hierarchical} { lappend values [attribute $cell cell $attribute] }
            puts $out [join $values \t]
        }
        if {[string match RAMSP*X16 $reference]} {
            set clk [get_pins -quiet $name/CLK]
            if {[sizeof_collection $clk]} {
                set cone {}
                if {[llength [info commands all_fanin]] && ![catch {all_fanin -to $clk -flat -levels 3 -only_cells} cone]} {
                    report [format macro_%03d_clock_cone.rpt $index] [list report_cell $cone]
                } else { note [format macro_%03d_clock_cone.rpt $index] UNAVAILABLE "all_fanin collection failed: $cone" }
                report [format macro_%03d_clock_net.rpt $index] [list report_net -connections -verbose [get_nets -quiet -of_objects $clk]]
            } else { note $name/CLK UNAVAILABLE "macro clock pin missing" }
            incr index
        }
    }
    close $out
    note macro_gate_inventory.tsv COMPLETED "macro_count=$index; named handwritten gates are not automatically recognized ICGs"
}
proc kwt_diag::structure {path} {
    start $path mapped_connections
    introspection
    settings
    gating
    foreach task {net_loads macro_cones} {
        if {[catch {kwt_diag::$task} message]} { note $task UNAVAILABLE $message }
    }
    finish
}
proc kwt_diag::activity_point {out object kind index} {
    variable directory
    set name [get_object_name $object]
    set raw "UNAVAILABLE:get_switching_activity not installed"
    if {[llength [info commands get_switching_activity]]} {
        if {[catch {redirect -variable raw {get_switching_activity $object -related_clock}} message]} { set raw "UNAVAILABLE:$message" }
    }
    if {[string trim $raw] eq ""} { set raw "UNAVAILABLE:command_printed_no_activity_record" }
    set relative [format raw_activity/point_%05d.rpt $index]
    set record [open [file join $directory $relative] w]
    puts $record "kind=$kind\nobject=$name\n$raw"
    close $record
    set values [list $kind $name $relative]
    foreach attribute {toggle_rate static_probability switching_activity_source activity_source} { lappend values [attribute $object pin_or_port $attribute] }
    set hints {}
    foreach word {default propagat annotat user} {
        if {[string match -nocase *${word}* $raw]} { lappend hints raw_contains_$word }
    }
    if {![llength $hints]} { set hints SOURCE_UNAVAILABLE_inspect_report_activity_driver }
    lappend values [join $hints ,]
    puts $out [join $values \t]
}
proc kwt_diag::activity_points {} {
    variable directory
    file mkdir [file join $directory raw_activity]
    set out [open [file join $directory clock_macro_activity.tsv] w]
    puts $out "kind\tobject\traw_record\ttoggle_rate_attribute\tstatic_probability_attribute\tswitching_activity_source\tactivity_source\tsource_text_hints_NOT_certification"
    set index 0
    array set seen {}
    set collections [list [list root_clock [get_ports -quiet clk]] [list register_clock [all_registers -clock_pins]]]
    foreach_in_collection cell [get_cells -hierarchical -quiet *] {
        set name [get_object_name $cell]
        set reference [attribute $cell cell ref_name]
        if {[string match RAMSP*X16 $reference]} {
            foreach suffix {CLK CEN GWEN RET1N} {
                set pin [get_pins -quiet $name/$suffix]
                if {[sizeof_collection $pin]} { lappend collections [list macro_control $pin] } else { note $name/$suffix UNAVAILABLE "macro control pin missing" }
            }
            set clk [get_pins -quiet $name/CLK]
            if {[sizeof_collection $clk]} {
                # Include the actual driver gate output even if DC renamed the gate.
                set nets [get_nets -quiet -of_objects $clk]
                lappend collections [list macro_clock_net_pin [get_pins -quiet -of_objects $nets]]
            }
        }
        if {[regexp -nocase {clock_gate|gated_clock|clk_gate|clkgate} $name]} {
            lappend collections [list named_gate_pin [get_pins -quiet -of_objects $cell]]
        }
    }
    foreach item $collections {
        lassign $item kind objects
        foreach_in_collection object $objects {
            set name [get_object_name $object]
            if {[info exists seen($name)]} { continue }
            set seen($name) 1
            activity_point $out $object $kind $index
            incr index
        }
    }
    close $out
    note clock_macro_activity.tsv COMPLETED "points=$index; raw source text and raw reports are authoritative; attributes are version dependent"
}
proc kwt_diag::activity {path phase {power 0}} {
    start $path $phase
    report coverage_hierarchy.rpt {report_saif -hierarchy}
    report coverage_rtl_hierarchy.rpt {report_saif -hierarchy -rtl_saif}
    report missing_rtl_hierarchy.rpt {report_saif -hierarchy -rtl_saif -missing}
    report activity_driver.rpt {report_activity -driver}
    report activity_verbose.rpt {report_activity -verbose}
    if {$power} {
        report power_summary.rpt {report_power}
        report power_hierarchy.rpt {report_power -hierarchy -levels 6 -nosplit}
        # These roots are disjoint. Parent totals and descendants must not be added.
        foreach pair {{cpu cpu} {shared bus/shared} {accelerator bus/accelerator}} {
            lassign $pair group root
            set cells [get_cells -quiet $root]
            if {[sizeof_collection $cells]} {
                report power_group_${group}.rpt [list report_power -cell -only $cells -nosplit]
            } else { note power_group_${group}.rpt UNAVAILABLE "preserved hierarchy $root absent; inspect power_hierarchy.rpt" }
        }
        set macros [get_cells -hierarchical -quiet -filter {ref_name =~ RAMSP*X16}]
        if {[sizeof_collection $macros]} { report power_macros.rpt [list report_power -cell -only $macros -nosplit] }
        # report_power can propagate missing activity: capture its result below.
        report coverage_after_power.rpt {report_saif -hierarchy}
        report activity_driver_after_power.rpt {report_activity -driver}
    }
    if {[catch {activity_points} message]} { note clock_macro_activity.tsv UNAVAILABLE $message }
    finish
}