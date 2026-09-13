// Fixed divide-by-two clock generator used only by the qualification wrapper.
// The implementation and its SDC declaration are frozen experiment inputs.

`default_nettype none

module nebula_clock_div2 (
    input  wire clk_in,
    input  wire reset,
    output reg  clk_out
);
    always @(posedge clk_in or posedge reset) begin
        if (reset)
            clk_out <= 1'b0;
        else
            clk_out <= ~clk_out;
    end
endmodule

`default_nettype wire
