`timescale 1ns / 1ps

module rtl_benchmark_top #(
    parameter int DATA_WIDTH = 32,
    parameter int NUM_MACS   = 20
)(
    // 5 independent master asynchronous clocks
    input  logic [4:0] clk_m,
    
    // Active low asynchronous reset (can be tied to a single reset source, 
    // though in reality would be synchronized per domain)
    input  logic       rst_n,

    // Primary Input (goes into Domain 0)
    input  logic                  in_valid,
    input  logic [DATA_WIDTH-1:0] in_data,

    // Primary Output (comes from Domain 4)
    output logic                  out_valid,
    output logic [DATA_WIDTH-1:0] out_data
);

    // Generated clocks
    logic [4:0] clk_g;

    // Reset synchronizers per master clock domain
    logic [4:0] rst_m_n_sync;
    // Reset synchronizers per generated clock domain
    logic [4:0] rst_g_n_sync;

    // Data pathways
    logic                  core_valid_out [0:4];
    logic [DATA_WIDTH-1:0] core_data_out  [0:4];

    logic                  fifo_rd_en    [0:4];
    logic                  fifo_empty    [0:4];
    logic [DATA_WIDTH-1:0] fifo_data_out [0:4];
    logic                  fifo_full     [0:4];

    // Clock division ratios: 2, 3, 4, 5, 8
    localparam int DIV_RATIOS [0:4] = '{2, 3, 4, 5, 8};

    genvar i;
    generate
        for (i = 0; i < 5; i++) begin : gen_domains
            // 1. Clock Divider (Master -> Generated)
            clock_divider #(
                .DIV_RATIO(DIV_RATIOS[i])
            ) u_clk_div (
                .clk_in (clk_m[i]),
                .rst_n  (rst_n),    // simple async reset for divider
                .clk_out(clk_g[i])
            );

            // Reset synchronization for the generated clock
            cdc_sync_bit u_rst_sync_g (
                .clk_dest  (clk_g[i]),
                .rst_dest_n(1'b1), // No reset for the synchronizer itself
                .async_in  (rst_n),
                .sync_out  (rst_g_n_sync[i])
            );

            // 2. Heavy Logic Core
            logic                  core_in_valid;
            logic [DATA_WIDTH-1:0] core_in_data;

            if (i == 0) begin : gen_input_domain
                // Domain 0 takes primary inputs
                assign core_in_valid = in_valid;
                assign core_in_data  = in_data;
            end else begin : gen_internal_domain
                // Domain 1..4 takes inputs from previous domain's FIFO
                assign fifo_rd_en[i-1] = ~fifo_empty[i-1];
                
                always_ff @(posedge clk_g[i] or negedge rst_g_n_sync[i]) begin
                    if (!rst_g_n_sync[i]) begin
                        core_in_valid <= 1'b0;
                        core_in_data  <= '0;
                    end else begin
                        core_in_valid <= fifo_rd_en[i-1];
                        core_in_data  <= fifo_data_out[i-1];
                    end
                end
            end

            heavy_logic_core #(
                .DATA_WIDTH(DATA_WIDTH),
                .NUM_MACS(NUM_MACS)
            ) u_heavy_logic (
                .clk      (clk_g[i]),
                .rst_n    (rst_g_n_sync[i]),
                .in_valid (core_in_valid),
                .in_data  (core_in_data),
                .out_valid(core_valid_out[i]),
                .out_data (core_data_out[i])
            );

            // 3. Asynchronous FIFO (crossing to next domain)
            // We only need 4 FIFOs (0->1, 1->2, 2->3, 3->4). Domain 4 goes to primary output.
            if (i < 4) begin : gen_cdc_fifo
                async_fifo #(
                    .DATA_WIDTH(DATA_WIDTH),
                    .ADDR_WIDTH(4)
                ) u_cdc_fifo (
                    .wr_clk  (clk_g[i]),
                    .wr_rst_n(rst_g_n_sync[i]),
                    .wr_en   (core_valid_out[i]),
                    .wr_data (core_data_out[i]),
                    .wr_full (fifo_full[i]),

                    .rd_clk  (clk_g[i+1]),
                    .rd_rst_n(rst_g_n_sync[i+1]),
                    .rd_en   (fifo_rd_en[i]),
                    .rd_data (fifo_data_out[i]),
                    .rd_empty(fifo_empty[i])
                );
            end
        end
    endgenerate

    // Primary Output from Domain 4
    always_ff @(posedge clk_g[4] or negedge rst_g_n_sync[4]) begin
        if (!rst_g_n_sync[4]) begin
            out_valid <= 1'b0;
            out_data  <= '0;
        end else begin
            out_valid <= core_valid_out[4];
            out_data  <= core_data_out[4];
        end
    end

endmodule
