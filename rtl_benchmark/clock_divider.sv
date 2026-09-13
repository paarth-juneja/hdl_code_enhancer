`timescale 1ns / 1ps

module clock_divider #(
    parameter int DIV_RATIO = 2 // Division ratio (must be >= 2)
)(
    input  logic clk_in,
    input  logic rst_n,
    output logic clk_out
);

    generate
        if (DIV_RATIO <= 1) begin : gen_div1
            assign clk_out = clk_in;
        end else if (DIV_RATIO % 2 == 0) begin : gen_even
            // Even division
            localparam int MAX_COUNT = (DIV_RATIO / 2) - 1;
            logic [$clog2(DIV_RATIO)-1:0] count;
            logic out_reg;

            always_ff @(posedge clk_in or negedge rst_n) begin
                if (!rst_n) begin
                    count <= '0;
                    out_reg <= 1'b0;
                end else begin
                    if (count == MAX_COUNT[$clog2(DIV_RATIO)-1:0]) begin
                        count <= '0;
                        out_reg <= ~out_reg;
                    end else begin
                        count <= count + 1'b1;
                    end
                end
            end
            assign clk_out = out_reg;

        end else begin : gen_odd
            // Odd division (e.g. 3, 5, 7) - close to 50% duty cycle
            localparam int MAX_COUNT = DIV_RATIO - 1;
            localparam int TOGGLE_COUNT = DIV_RATIO / 2;
            
            logic [$clog2(DIV_RATIO)-1:0] count;
            logic out_pos, out_neg;

            always_ff @(posedge clk_in or negedge rst_n) begin
                if (!rst_n) begin
                    count <= '0;
                    out_pos <= 1'b0;
                end else begin
                    if (count == MAX_COUNT[$clog2(DIV_RATIO)-1:0]) begin
                        count <= '0;
                    end else begin
                        count <= count + 1'b1;
                    end
                    
                    if (count == '0 || count == TOGGLE_COUNT[$clog2(DIV_RATIO)-1:0]) begin
                        out_pos <= ~out_pos;
                    end
                end
            end

            always_ff @(negedge clk_in or negedge rst_n) begin
                if (!rst_n) begin
                    out_neg <= 1'b0;
                end else begin
                    out_neg <= out_pos;
                end
            end

            // Just toggle, using typical odd divider approach
            assign clk_out = (DIV_RATIO > 1) ? (out_pos | out_neg) : clk_in;
        end
    endgenerate

endmodule
