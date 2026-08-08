// clk_div.v — programmable integer clock divider producing one generated
// clock per master domain.
//
// PROTECTED REGION. Listed under `protected_paths` in nebula.project.yaml.
//
// Why protected: the output of this module is declared to OpenSTA via
// create_generated_clock in constraints/nebula.sdc. Changing the divider
// changes the timing environment itself, which would make every baseline and
// candidate measurement in the experiment non-comparable. There is no
// transformation here that could be honestly reported as an optimization.

`default_nettype none

module clk_div #(
    parameter integer RW = 4
) (
    input  wire           clk_in,
    input  wire           rst_n,
    input  wire           enable,
    input  wire [RW-1:0]  ratio_in,   // half-period count, minimum 1
    output reg            clk_out
);

    reg [RW-1:0] ratio_reg;
    reg [RW-1:0] cnt;

    always @(posedge clk_in or negedge rst_n) begin
        if (!rst_n) begin
            ratio_reg <= {{(RW-1){1'b0}}, 1'b1};
            cnt       <= {RW{1'b0}};
            clk_out   <= 1'b0;
        end else if (!enable) begin
            cnt     <= {RW{1'b0}};
            clk_out <= 1'b0;
        end else if (ratio_reg != ratio_in) begin
            ratio_reg <= (ratio_in == {RW{1'b0}}) ? {{(RW-1){1'b0}}, 1'b1} : ratio_in;
            cnt       <= {RW{1'b0}};
        end else if (cnt >= (ratio_reg - 1'b1)) begin
            cnt     <= {RW{1'b0}};
            clk_out <= ~clk_out;
        end else begin
            cnt <= cnt + 1'b1;
        end
    end

endmodule

`default_nettype wire
