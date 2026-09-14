// Observable auxiliary datapath for the fourth and fifth asynchronous domains.
// The deliberately linear XOR reduction is cycle-exactly reassociable, giving
// the optimization engine a genuine logic-depth target. CDC lives elsewhere.

`default_nettype none

module nebula_aux_domain #(
    parameter integer WIDTH = 3328
) (
    input  wire              clk,
    input  wire              reset,
    input  wire              load,
    input  wire       [31:0] seed,
    output wire       [31:0] digest
);
    reg [WIDTH-1:0] state;

    wire [31:0] mix0 = state[31:0]   ^ state[63:32];
    wire [31:0] mix1 = mix0          ^ state[95:64];
    wire [31:0] mix2 = mix1          ^ state[127:96];
    wire [31:0] mix3 = mix2          ^ state[159:128];
    wire [31:0] mix4 = mix3          ^ state[191:160];
    wire [31:0] mix5 = mix4          ^ state[223:192];
    wire [31:0] mix6 = mix5          ^ state[255:224];

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            state <= {{(WIDTH-32){1'b0}}, 32'h1};
        end else begin
            state[WIDTH-1:32] <= state[WIDTH-33:0];
            if (load)
                state[31:0] <= seed;
            else
                state[31:0] <= mix6;
        end
    end

    assign digest = state[31:0] ^ state[WIDTH-1:WIDTH-32];
endmodule

`default_nettype wire
