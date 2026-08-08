// nebula_top.v — tiny "truth fixture" top level.
//
// Two asynchronous master clocks, one generated clock per master, one CDC
// handshake between them, and one optimizable datapath. This is the small
// design used for rapid regression of the orchestrator itself; the qualified
// benchmark (five master domains, ~50K cells) is a separate configuration
// that reuses the same module structure.
//
// Domain map:
//   clk_a (master) -> clk_a_div (generated) -> dsp_core, cdc_sync source side
//   clk_b (master) -> clk_b_div (generated) -> cdc_sync destination side

`default_nettype none

module nebula_top #(
    parameter integer W = 16
) (
    input  wire           clk_a,
    input  wire           clk_b,
    input  wire           rst_a_n,
    input  wire           rst_b_n,

    input  wire           div_enable,
    input  wire [3:0]     ratio_a,
    input  wire [3:0]     ratio_b,

    input  wire           in_valid,
    input  wire [W-1:0]   a0, a1, a2, a3, a4, a5, a6, a7,
    input  wire [2:0]     mode,

    output wire           src_ready,
    output wire [W-1:0]   dst_data,
    output wire           dst_valid
);

    wire clk_a_div;
    wire clk_b_div;

    // Generated clocks -- protected.
    clk_div #(.RW(4)) u_div_a (
        .clk_in   (clk_a),
        .rst_n    (rst_a_n),
        .enable   (div_enable),
        .ratio_in (ratio_a),
        .clk_out  (clk_a_div)
    );

    clk_div #(.RW(4)) u_div_b (
        .clk_in   (clk_b),
        .rst_n    (rst_b_n),
        .enable   (div_enable),
        .ratio_in (ratio_b),
        .clk_out  (clk_b_div)
    );

    // Optimizable datapath.
    wire [W+3:0] acc_out;
    wire         acc_valid;

    dsp_core #(.W(W)) u_dsp (
        .clk       (clk_a_div),
        .rst_n     (rst_a_n),
        .in_valid  (in_valid),
        .a0(a0), .a1(a1), .a2(a2), .a3(a3),
        .a4(a4), .a5(a5), .a6(a6), .a7(a7),
        .mode      (mode),
        .acc_out   (acc_out),
        .out_valid (acc_valid)
    );

    // Clock-domain crossing -- protected.
    cdc_sync #(.DW(W)) u_cdc (
        .src_clk   (clk_a_div),
        .src_rst_n (rst_a_n),
        .src_valid (acc_valid),
        .src_data  (acc_out[W-1:0]),
        .src_ready (src_ready),
        .dst_clk   (clk_b_div),
        .dst_rst_n (rst_b_n),
        .dst_data  (dst_data),
        .dst_valid (dst_valid)
    );

endmodule

`default_nettype wire
