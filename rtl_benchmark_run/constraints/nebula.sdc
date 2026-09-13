# Timing constraints for rtl_benchmark_top
set_units -time ns -capacitance pF -resistance kOhm

# Five independent 100 MHz master clocks.
create_clock -name {clk_m[0]} -period 10.0 [get_ports {clk_m[0]}]
create_clock -name {clk_m[1]} -period 10.0 [get_ports {clk_m[1]}]
create_clock -name {clk_m[2]} -period 10.0 [get_ports {clk_m[2]}]
create_clock -name {clk_m[3]} -period 10.0 [get_ports {clk_m[3]}]
create_clock -name {clk_m[4]} -period 10.0 [get_ports {clk_m[4]}]

# Generated clocks with RTL divider ratios 2, 3, 4, 5 and 8.
create_generated_clock -name {clk_g[0]} \
    -source [get_ports {clk_m[0]}] \
    -divide_by 2 [get_ports {clk_g[0]}]

create_generated_clock -name {clk_g[1]} \
    -source [get_ports {clk_m[1]}] \
    -divide_by 3 [get_ports {clk_g[1]}]

create_generated_clock -name {clk_g[2]} \
    -source [get_ports {clk_m[2]}] \
    -divide_by 4 [get_ports {clk_g[2]}]

create_generated_clock -name {clk_g[3]} \
    -source [get_ports {clk_m[3]}] \
    -divide_by 5 [get_ports {clk_g[3]}]

create_generated_clock -name {clk_g[4]} \
    -source [get_ports {clk_m[4]}] \
    -divide_by 8 [get_ports {clk_g[4]}]

# Each generated clock is synchronous with its parent.
# The five parent/generated-clock domains are asynchronous to one another.
set_clock_groups -asynchronous \
    -group {{clk_m[0]} {clk_g[0]}} \
    -group {{clk_m[1]} {clk_g[1]}} \
    -group {{clk_m[2]} {clk_g[2]}} \
    -group {{clk_m[3]} {clk_g[3]}} \
    -group {{clk_m[4]} {clk_g[4]}}

# Explicit benchmark environment assumptions.
set_clock_uncertainty 0.100 [all_clocks]
set_clock_transition 0.080 [all_clocks]

# Primary input enters generated-clock domain 0.
set_input_delay 1.0 -clock {clk_g[0]} \
    [get_ports {in_valid in_data*}]

# Primary output leaves generated-clock domain 4.
set_output_delay 1.0 -clock {clk_g[4]} \
    [get_ports {out_valid out_data*}]

set_driving_cell -lib_cell BUF_X1 \
    [get_ports {in_valid in_data*}]

set_load 0.020 [get_ports {out_valid out_data*}]

# rst_n is an asynchronous reset, not a timed data input.
set_false_path -from [get_ports rst_n]

# No multicycle paths are declared.
