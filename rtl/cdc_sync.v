// cdc_sync.v — four-phase request/acknowledge handshake across two
// asynchronous clock domains, with two-flop synchronizers on the control bits.
//
// PROTECTED REGION. The whole file is listed under `protected_paths` in
// nebula.project.yaml. orchestrator/patcher.py rejects any candidate diff whose
// changed lines fall inside it, regardless of what the model proposes.
//
// Why protected: open-source formal equivalence checks logic equivalence, not
// metastability behaviour. A change that looks like an improvement here (for
// example collapsing a synchronizer stage, or "fixing" the unsynchronized data
// bus) would pass EQY and still be a silicon bug. The data bus is intentionally
// NOT synchronized -- it is held stable by the handshake protocol for the whole
// time req is asserted, which is the standard and correct construction.

`default_nettype none

module cdc_sync #(
    parameter integer DW = 16
) (
    // Source domain
    input  wire           src_clk,
    input  wire           src_rst_n,
    input  wire           src_valid,
    input  wire [DW-1:0]  src_data,
    output reg            src_ready,

    // Destination domain
    input  wire           dst_clk,
    input  wire           dst_rst_n,
    output reg  [DW-1:0]  dst_data,
    output reg            dst_valid
);

    localparam [1:0] S_IDLE       = 2'd0;
    localparam [1:0] S_ASSERT_REQ = 2'd1;
    localparam [1:0] S_CLEAR_REQ  = 2'd2;

    localparam [1:0] D_IDLE       = 2'd0;
    localparam [1:0] D_ASSERT_ACK = 2'd1;

    reg  [1:0]    src_state;
    reg  [1:0]    dst_state;
    reg           req;
    reg           ack;
    reg [DW-1:0]  data_reg;

    // Two-flop synchronizers. Never reduce these to one stage.
    reg req_meta, req_sync;
    reg ack_meta, ack_sync;

    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            req_meta <= 1'b0;
            req_sync <= 1'b0;
        end else begin
            req_meta <= req;
            req_sync <= req_meta;
        end
    end

    always @(posedge src_clk or negedge src_rst_n) begin
        if (!src_rst_n) begin
            ack_meta <= 1'b0;
            ack_sync <= 1'b0;
        end else begin
            ack_meta <= ack;
            ack_sync <= ack_meta;
        end
    end

    // Source-domain handshake FSM.
    always @(posedge src_clk or negedge src_rst_n) begin
        if (!src_rst_n) begin
            src_state <= S_IDLE;
            req       <= 1'b0;
            src_ready <= 1'b1;
            data_reg  <= {DW{1'b0}};
        end else begin
            case (src_state)
                S_IDLE: begin
                    if (src_valid) begin
                        data_reg  <= src_data;   // stable while req is high
                        req       <= 1'b1;
                        src_ready <= 1'b0;
                        src_state <= S_ASSERT_REQ;
                    end
                end
                S_ASSERT_REQ: begin
                    if (ack_sync) begin
                        req       <= 1'b0;
                        src_state <= S_CLEAR_REQ;
                    end
                end
                S_CLEAR_REQ: begin
                    if (!ack_sync) begin
                        src_ready <= 1'b1;
                        src_state <= S_IDLE;
                    end
                end
                default: src_state <= S_IDLE;
            endcase
        end
    end

    // Destination-domain handshake FSM.
    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            dst_state <= D_IDLE;
            ack       <= 1'b0;
            dst_valid <= 1'b0;
            dst_data  <= {DW{1'b0}};
        end else begin
            dst_valid <= 1'b0;
            case (dst_state)
                D_IDLE: begin
                    if (req_sync) begin
                        dst_data  <= data_reg;
                        dst_valid <= 1'b1;
                        ack       <= 1'b1;
                        dst_state <= D_ASSERT_ACK;
                    end
                end
                D_ASSERT_ACK: begin
                    if (!req_sync) begin
                        ack       <= 1'b0;
                        dst_state <= D_IDLE;
                    end
                end
                default: dst_state <= D_IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
