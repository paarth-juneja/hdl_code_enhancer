# Exploratory nangate45 scenario, NOT the upstream ASAP7 constraints.
# Only input clocks are qualified here. MDC has a runtime-programmable ratio;
# generated-clock operating modes still require separate qualification.
create_clock -name wb_clk -period 10 [get_ports wb_clk_i]
create_clock -name tx_clk -period 40 [get_ports mtx_clk_pad_i]
create_clock -name rx_clk -period 40 [get_ports mrx_clk_pad_i]
set_clock_groups -asynchronous -group {wb_clk} -group {tx_clk} -group {rx_clk}
# Bus/control inputs default to WB timing. PHY receive data belongs to RX.
foreach p [all_inputs] {
    set n [get_full_name $p]
    if {$n in {wb_clk_i mtx_clk_pad_i mrx_clk_pad_i wb_rst_i}} {continue}
    if {[string match {mrxd*} $n] || $n eq "mrxerr_pad_i"} {
        set_input_delay 2 -clock rx_clk $p
    } else {
        set_input_delay 2 -clock wb_clk $p
    }
}
foreach p [all_outputs] {
    set n [get_full_name $p]
    if {$n eq "mdc_pad_o"} {continue}
    if {[string match {mtx*} $n]} {
        set_output_delay 2 -clock tx_clk $p
    } else {
        set_output_delay 2 -clock wb_clk $p
    }
}
set_false_path -from [get_ports wb_rst_i]

