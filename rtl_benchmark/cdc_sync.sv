`timescale 1ns / 1ps

// 2-Flop Synchronizer for scalar signals
module cdc_sync_bit (
    input  logic clk_dest,
    input  logic rst_dest_n,
    input  logic async_in,
    output logic sync_out
);
    logic sync_q1;
    logic sync_q2;

    always_ff @(posedge clk_dest or negedge rst_dest_n) begin
        if (!rst_dest_n) begin
            sync_q1 <= 1'b0;
            sync_q2 <= 1'b0;
        end else begin
            sync_q1 <= async_in;
            sync_q2 <= sync_q1;
        end
    end

    assign sync_out = sync_q2;
endmodule

// Asynchronous FIFO for vector signals
module async_fifo #(
    parameter int DATA_WIDTH = 32,
    parameter int ADDR_WIDTH = 4 // Depth = 2^ADDR_WIDTH
)(
    // Write Domain
    input  logic                  wr_clk,
    input  logic                  wr_rst_n,
    input  logic                  wr_en,
    input  logic [DATA_WIDTH-1:0] wr_data,
    output logic                  wr_full,

    // Read Domain
    input  logic                  rd_clk,
    input  logic                  rd_rst_n,
    input  logic                  rd_en,
    output logic [DATA_WIDTH-1:0] rd_data,
    output logic                  rd_empty
);

    localparam int DEPTH = 1 << ADDR_WIDTH;

    // Memory array
    logic [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    // Pointers
    logic [ADDR_WIDTH:0] wr_ptr, wr_ptr_next;
    logic [ADDR_WIDTH:0] wr_ptr_gray, wr_ptr_gray_next;
    logic                  wr_full_next;
    
    logic [ADDR_WIDTH:0] rd_ptr, rd_ptr_next;
    logic [ADDR_WIDTH:0] rd_ptr_gray, rd_ptr_gray_next;
    logic                  rd_empty_next;

    // Synchronized pointers
    logic [ADDR_WIDTH:0] wr_ptr_gray_sync1, wr_ptr_gray_sync2;
    logic [ADDR_WIDTH:0] rd_ptr_gray_sync1, rd_ptr_gray_sync2;

    // Write Logic
    assign wr_ptr_next = (wr_en && !wr_full) ? (wr_ptr + 1'b1) : wr_ptr;
    assign wr_ptr_gray_next = (wr_ptr_next >> 1) ^ wr_ptr_next;

    always_ff @(posedge wr_clk or negedge wr_rst_n) begin
        if (!wr_rst_n) begin
            wr_ptr      <= '0;
            wr_ptr_gray <= '0;
            wr_full     <= 1'b0;
        end else begin
            wr_ptr      <= wr_ptr_next;
            wr_ptr_gray <= wr_ptr_gray_next;
            wr_full     <= wr_full_next;
            if (wr_en && !wr_full) begin
                mem[wr_ptr[ADDR_WIDTH-1:0]] <= wr_data;
            end
        end
    end

    // Read Logic
    assign rd_ptr_next = (rd_en && !rd_empty) ? (rd_ptr + 1'b1) : rd_ptr;
    assign rd_ptr_gray_next = (rd_ptr_next >> 1) ^ rd_ptr_next;

    always_ff @(posedge rd_clk or negedge rd_rst_n) begin
        if (!rd_rst_n) begin
            rd_ptr      <= '0;
            rd_ptr_gray <= '0;
            rd_empty    <= 1'b1;
        end else begin
            rd_ptr      <= rd_ptr_next;
            rd_ptr_gray <= rd_ptr_gray_next;
            rd_empty    <= rd_empty_next;
        end
    end

    assign rd_data = mem[rd_ptr[ADDR_WIDTH-1:0]];

    // Synchronize Read Pointer to Write Domain
    always_ff @(posedge wr_clk or negedge wr_rst_n) begin
        if (!wr_rst_n) begin
            rd_ptr_gray_sync1 <= '0;
            rd_ptr_gray_sync2 <= '0;
        end else begin
            rd_ptr_gray_sync1 <= rd_ptr_gray;
            rd_ptr_gray_sync2 <= rd_ptr_gray_sync1;
        end
    end

    // Synchronize Write Pointer to Read Domain
    always_ff @(posedge rd_clk or negedge rd_rst_n) begin
        if (!rd_rst_n) begin
            wr_ptr_gray_sync1 <= '0;
            wr_ptr_gray_sync2 <= '0;
        end else begin
            wr_ptr_gray_sync1 <= wr_ptr_gray;
            wr_ptr_gray_sync2 <= wr_ptr_gray_sync1;
        end
    end

    // Empty / Full logic
    assign wr_full_next =
        (wr_ptr_gray_next == {
            ~rd_ptr_gray_sync2[ADDR_WIDTH:ADDR_WIDTH-1],
            rd_ptr_gray_sync2[ADDR_WIDTH-2:0]
        });
    assign rd_empty_next = (rd_ptr_gray_next == wr_ptr_gray_sync2);

endmodule
