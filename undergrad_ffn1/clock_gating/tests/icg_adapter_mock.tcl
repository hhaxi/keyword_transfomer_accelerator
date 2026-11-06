# Mock ONLY the DC collection/library API. This is not a DC/library validation.
array set attrs {}
set libcells {};set wrapper_names {};set disabled_names {}
proc fail {msg} { error $msg }
proc get_object_name {x} { return $x }
proc sizeof_collection {x} { return [llength $x] }
proc foreach_in_collection {variable collection body} {
 set code [catch {uplevel 1 [list foreach $variable $collection $body]} result options]
 if {$code==2} { dict incr options -level }
 return -options $options $result
}
proc get_attribute {args} {
 global attrs
 set obj [lindex $args end-1];set attr [lindex $args end]
 if {![info exists attrs($obj,$attr)]} { error "missing mock attribute" }
 return $attrs($obj,$attr)
}
proc get_lib_cells {args} { global libcells;return $libcells }
proc get_lib_pins {args} {
 global attrs
 set glob [lindex $args end];set pins {}
 foreach key [array names attrs *,direction] {
  set name [string range $key 0 end-10]
  if {[string match $glob $name]} { lappend pins $name }
 }
 return [lsort $pins]
}
proc get_cells {args} {
 global wrapper_names attrs
 if {[lsearch -exact $args -filter]>=0} { return $wrapper_names }
 set name [lindex $args end]
 if {[info exists attrs($name,ref_name)]} { return [list $name] }
 return {}
}
proc set_dont_touch {cells value} { global disabled_names;set disabled_names $cells }
proc redirect {args} {
 set file [lindex $args 1];set script [lindex $args end]
 set f [open $file w];puts $f "MOCK REPORT, NO DC EXECUTION";close $f
 uplevel 1 $script
}
proc report_clock_gating {} { return "mock only" }
proc mock_cell {name kind area {test 1}} {
 global attrs libcells
 lappend libcells $name
 set attrs($name,clock_gating_integrated_cell) $kind
 set attrs($name,area) $area;set attrs($name,dont_use) false
 foreach {pin role direction} {CK clock input E enable input Q out output} {
  set attrs($name/$pin,clock_gate_${role}_pin) true
  set attrs($name/$pin,direction) $direction
 }
 if {$test} {
  set attrs($name/TE,clock_gate_test_pin) true
  set attrs($name/TE,direction) input
 }
}
proc mock_expected {count} {
 global backend_root
 set f [open [file join $backend_root config clock_gating_config.tcl] w]
 puts $f "set kwt_cg_expected $count";close $f
}
