// Toggle synchronizer for commands entering an auxiliary clock domain.
// This module is protected from optimization because it implements CDC logic.

`default_nettype none

module nebula_aux_cdc (
    input  wire clk,
    input  wire reset,
    input  wire command_toggle_async,
    output reg  command_pulse,
    output wire response_toggle
);
    reg command_meta;
    reg command_sync;
    reg command_seen;

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            command_meta <= 1'b0;
            command_sync <= 1'b0;
            command_seen <= 1'b0;
            command_pulse <= 1'b0;
        end else begin
            command_meta <= command_toggle_async;
            command_sync <= command_meta;
            command_pulse <= (command_sync != command_seen);
            if (command_sync != command_seen)
                command_seen <= command_sync;
        end
    end

    assign response_toggle = command_seen;
endmodule

`default_nettype wire
