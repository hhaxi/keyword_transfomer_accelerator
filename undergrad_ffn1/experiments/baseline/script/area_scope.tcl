# Area helpers for a mapped reference SoC. Never guess missing area as zero.
proc kwt_valid_area {value} {
    if {![string is double -strict $value]} { return 0 }
    if {[catch {expr {$value>=0.0 && $value<Inf}} valid]} { return 0 }
    return $valid
}
proc kwt_leaf_area {cell} {
    set area {}
    catch { set area [get_attribute -quiet $cell area] }
    if {[kwt_valid_area $area]} { return [list $area instance] }
    # Use the actual linked reference, not a wildcard that could select another
    # library/corner with the same reference name.
    set references {}
    catch { set references [get_lib_cells -quiet -of_objects $cell] }
    if {[sizeof_collection $references]==1} {
        set area {}
        catch { set area [get_attribute -quiet $references area] }
        if {[kwt_valid_area $area]} { return [list $area library] }
    }
    return [list {} unavailable]
}
proc kwt_write_scope_area_report {path} {
    array set scope_area {added 0.0 cpu 0.0 shared 0.0}
    array set scope_count {added 0 cpu 0 shared 0}
    array set unknown_count {added 0 cpu 0 shared 0}
    array set area_sources {instance 0 library 0 unavailable 0}
    set missing {}
    set complete 1
    # Sum leaves only; hierarchical areas overlap.
    foreach_in_collection cell [get_cells -hierarchical -filter {is_hierarchical == false}] {
        set name [get_object_name $cell]
        set category added
        if {[string match "cpu/*" $name]} { set category cpu }
        if {[string match "bus/shared/*" $name]} { set category shared }
        incr scope_count($category)
        lassign [kwt_leaf_area $cell] area source
        incr area_sources($source)
        if {$source eq "unavailable"} {
            set complete 0
            incr unknown_count($category)
            set reference UNKNOWN
            catch { set reference [get_attribute -quiet $cell ref_name] }
            lappend missing [list cell $name ref_name $reference category $category]
        } else {
            set scope_area($category) [expr {$scope_area($category)+$area}]
        }
    }
    foreach category {added cpu shared} {
        if {$scope_count($category)==0} { set complete 0 }
    }
    set out [open $path w]
    puts $out "status=[expr {$complete ? {COMPLETE} : {INCOMPLETE}}]"
    foreach category {added cpu shared} {
        set area UNKNOWN
        if {$scope_count($category)>0 && $unknown_count($category)==0} {
            set area $scope_area($category)
        }
        puts $out "$category leaves=$scope_count($category) area=$area known_area=$scope_area($category) unknown_leaves=$unknown_count($category)"
        if {$scope_count($category)==0} { puts $out "EMPTY_CATEGORY $category; inspect hierarchy" }
    }
    puts $out "Area sources: instance=$area_sources(instance) library=$area_sources(library) unavailable=$area_sources(unavailable)"
    foreach item $missing { puts $out "UNKNOWN_AREA $item" }
    puts $out "UNKNOWN area is not zero; known_area is a subtotal, not a complete category area."
    puts $out "Budget scope is added only. CPU includes ITCM/DTCM. Shared SRAM is separate."
    puts $out "Units follow libraries; SRAM macro areas must also be checked against official data."
    puts $out "Reference SoC excludes official fixed peripheral platform and analog blocks."
    close $out
    if {!$complete} { puts "KWT_AREA_SCOPE_INCOMPLETE: inspect $path; other reports will still be saved" }
    return $complete
}
