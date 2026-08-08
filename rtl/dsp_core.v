// dsp_core.v — accumulate-and-scale datapath.
//
// This module is the intended OPTIMIZATION TARGET. Everything here is
// combinational datapath logic in the clk_dsp domain: no clock generation,
// no reset restructuring, no clock-domain crossing. The patcher's
// protected-region check does not cover this file.
//
// The deliberate inefficiency is the linear accumulation chain below: eight
// terms summed sequentially give a logic depth proportional to the term count.
// A balanced adder tree computes the identical sum at roughly log2 depth,
// which is a cycle-exact transformation EQY can prove today.

`default_nettype none

module dsp_core #(
    parameter integer W = 16
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              in_valid,
    input  wire [W-1:0]      a0,
    input  wire [W-1:0]      a1,
    input  wire [W-1:0]      a2,
    input  wire [W-1:0]      a3,
    input  wire [W-1:0]      a4,
    input  wire [W-1:0]      a5,
    input  wire [W-1:0]      a6,
    input  wire [W-1:0]      a7,
    input  wire [2:0]        mode,
    output reg  [W+3:0]      acc_out,
    output reg               out_valid
);

    localparam integer AW = W + 4;

    // ---------------------------------------------------------------------
    // Linear accumulation chain (optimization target).
    // Depth here is 7 adders in series. A balanced tree is 3 levels.
    // ---------------------------------------------------------------------
    wire [AW-1:0] s0 = {{4{1'b0}}, a0};
    wire [AW-1:0] s1 = s0 + {{4{1'b0}}, a1};
    wire [AW-1:0] s2 = s1 + {{4{1'b0}}, a2};
    wire [AW-1:0] s3 = s2 + {{4{1'b0}}, a3};
    wire [AW-1:0] s4 = s3 + {{4{1'b0}}, a4};
    wire [AW-1:0] s5 = s4 + {{4{1'b0}}, a5};
    wire [AW-1:0] s6 = s5 + {{4{1'b0}}, a6};
    wire [AW-1:0] s7 = s6 + {{4{1'b0}}, a7};

    // ---------------------------------------------------------------------
    // Priority mux chain (secondary optimization target).
    // Written as a priority cascade although the conditions are mutually
    // exclusive, so it flattens to a parallel mux without changing behaviour.
    // ---------------------------------------------------------------------
    reg [AW-1:0] scaled;
    always @(*) begin
        if (mode == 3'd0)
            scaled = s7;
        else if (mode == 3'd1)
            scaled = s7 << 1;
        else if (mode == 3'd2)
            scaled = s7 << 2;
        else if (mode == 3'd3)
            scaled = s7 << 3;
        else if (mode == 3'd4)
            scaled = s7 >> 1;
        else if (mode == 3'd5)
            scaled = s7 >> 2;
        else if (mode == 3'd6)
            scaled = s7 - {{4{1'b0}}, a0};
        else
            scaled = {AW{1'b0}};
    end

    // ---------------------------------------------------------------------
    // Output registers. Latency is exactly one cycle and must stay that way:
    // every allowed transformation is declared cycle-exact.
    // ---------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc_out   <= {AW{1'b0}};
            out_valid <= 1'b0;
        end else begin
            acc_out   <= scaled;
            out_valid <= in_valid;
        end
    end

endmodule

`default_nettype wire
