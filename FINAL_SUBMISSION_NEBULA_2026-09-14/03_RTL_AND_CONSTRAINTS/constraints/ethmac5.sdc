# Exploratory five-domain qualification scenario for nebula_ethmac5_top.
set_units -time ns -capacitance pF -resistance kOhm

# The legacy MAC is intentionally relaxed here: Nebula's standalone screen has
# no placement-aware buffering and otherwise reports a ~100 ns high-fanout WB
# path that ORFS later repairs to >350 MHz. AUX0/AUX1 carry the optimization
# objective; WB/TX/RX remain constrained qualification domains.
create_clock -name wb_clk   -period 220.0 [get_ports wb_clk_i]
create_clock -name tx_clk   -period 40.0 [get_ports mtx_clk_pad_i]
create_clock -name rx_clk   -period 40.0 [get_ports mrx_clk_pad_i]
create_clock -name aux0_clk -period 0.45   [get_ports aux0_clk_i]
create_clock -name aux1_clk -period 0.5625 [get_ports aux1_clk_i]

create_generated_clock -name wb_clk_div2 \
    -source [get_ports wb_clk_i] -divide_by 2 [get_nets wb_clk_div2_o]
create_generated_clock -name tx_clk_div2 \
    -source [get_ports mtx_clk_pad_i] -divide_by 2 [get_nets tx_clk_div2_o]
create_generated_clock -name rx_clk_div2 \
    -source [get_ports mrx_clk_pad_i] -divide_by 2 [get_nets rx_clk_div2_o]
create_generated_clock -name aux0_clk_div2 \
    -source [get_ports aux0_clk_i] -divide_by 2 [get_nets aux0_clk_div2_o]
create_generated_clock -name aux1_clk_div2 \
    -source [get_ports aux1_clk_i] -divide_by 2 [get_nets aux1_clk_div2_o]

set_clock_groups -asynchronous \
    -group {wb_clk wb_clk_div2} \
    -group {tx_clk tx_clk_div2} \
    -group {rx_clk rx_clk_div2} \
    -group {aux0_clk aux0_clk_div2} \
    -group {aux1_clk aux1_clk_div2}

set_clock_uncertainty 0.10 [all_clocks]
set_clock_transition 0.08 [all_clocks]

set clock_ports {wb_clk_i mtx_clk_pad_i mrx_clk_pad_i aux0_clk_i aux1_clk_i}
foreach p [all_inputs] {
    set n [get_full_name $p]
    if {[lsearch -exact $clock_ports $n] >= 0 || $n eq "wb_rst_i"} {continue}
    if {[string match {mrxd*} $n] || $n eq "mrxerr_pad_i"} {
        set_input_delay 2.0 -clock rx_clk $p
    } elseif {[string match {aux0_*} $n]} {
        set_input_delay 0.2 -clock aux0_clk $p
    } elseif {[string match {aux1_*} $n]} {
        set_input_delay 0.2 -clock aux1_clk $p
    } else {
        set_input_delay 2.0 -clock wb_clk $p
    }
}

set generated_ports {wb_clk_div2_o tx_clk_div2_o rx_clk_div2_o aux0_clk_div2_o aux1_clk_div2_o}
foreach p [all_outputs] {
    set n [get_full_name $p]
    if {[lsearch -exact $generated_ports $n] >= 0} {continue}
    if {[string match {mtx*} $n]} {
        set_output_delay 2.0 -clock tx_clk $p
    } elseif {[string match {aux0_*} $n]} {
        set_output_delay 0.2 -clock aux0_clk $p
    } elseif {[string match {aux1_*} $n]} {
        set_output_delay 0.2 -clock aux1_clk $p
    } else {
        set_output_delay 2.0 -clock wb_clk $p
    }
}

set_driving_cell -lib_cell BUF_X1 [all_inputs]
set_load 0.020 [all_outputs]
set_false_path -from [get_ports wb_rst_i]
