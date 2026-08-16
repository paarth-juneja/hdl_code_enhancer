# nebula.sdc -- frozen timing environment for the truth fixture.
#
# FROZEN INPUT. This file is hashed into manifest.lock.json and is byte-identical
# for the baseline and for every candidate. orchestrator/policy.py refuses to emit
# a verdict if the SDC hash differs between the two runs being compared.

set_units -time ns -capacitance pF -resistance kOhm

# ---------------------------------------------------------------------------
# Master clocks -- asynchronous to each other.
# ---------------------------------------------------------------------------
create_clock -name clk_a -period 4.000 [get_ports clk_a]
create_clock -name clk_b -period 5.500 [get_ports clk_b]

# ---------------------------------------------------------------------------
# Generated clocks -- one per master, produced by clk_div.
#
# Anchored on the named nets, not on the divider output register pin. Yosys
# renames that register to an unstable auto-name (u_div_a/clk_out_reg/Q became
# _1750_), so a DC-style pin anchor resolves to nothing after synthesis and
# OpenSTA reports "empty ports/pins/nets argument". The nets clk_a_div and
# clk_b_div are declared in nebula_top.v and survive flattening on both paths.
# ---------------------------------------------------------------------------
create_generated_clock -name clk_a_div \
    -source [get_ports clk_a] -divide_by 2 [get_nets clk_a_div]

create_generated_clock -name clk_b_div \
    -source [get_ports clk_b] -divide_by 2 [get_nets clk_b_div]

# ---------------------------------------------------------------------------
# Asynchronous groups. clk_a* and clk_b* never have a meaningful phase
# relationship; paths between them are handled by the CDC handshake, not by STA.
# ---------------------------------------------------------------------------
set_clock_groups -asynchronous \
    -group {clk_a clk_a_div} \
    -group {clk_b clk_b_div}

# ---------------------------------------------------------------------------
# Uncertainty and transition.
# ---------------------------------------------------------------------------
set_clock_uncertainty 0.100 [get_clocks clk_a]
set_clock_uncertainty 0.100 [get_clocks clk_b]
set_clock_uncertainty 0.150 [get_clocks clk_a_div]
set_clock_uncertainty 0.150 [get_clocks clk_b_div]
set_clock_transition  0.080 [all_clocks]

# ---------------------------------------------------------------------------
# Portable replacement for Synopsys remove_from_collection, which OpenSTA does
# not implement. An OpenSTA collection is a plain Tcl list, so it is walked with
# foreach (NOT foreach_in_collection, also Synopsys-only) and each element's
# name is read with get_full_name.
# ---------------------------------------------------------------------------
proc data_inputs {exclude} {
    set kept {}
    foreach port [all_inputs] {
        if {[lsearch -exact $exclude [get_full_name $port]] < 0} {
            lappend kept $port
        }
    }
    return $kept
}

# ---------------------------------------------------------------------------
# IO timing. Every input and output is constrained so that "no violations"
# cannot be produced by an unconstrained path.
# ---------------------------------------------------------------------------
set_input_delay  -clock clk_a_div 0.600 \
    [data_inputs {clk_a clk_b rst_a_n rst_b_n}]
set_output_delay -clock clk_b_div 0.600 [all_outputs]

set_driving_cell -lib_cell BUF_X1 \
    [data_inputs {clk_a clk_b}]
set_load 0.020 [all_outputs]

set_false_path -from [get_ports {rst_a_n rst_b_n}]
