`timescale 1ns / 1ps

module heavy_logic_core #(
    parameter int DATA_WIDTH = 32,
    parameter int NUM_MACS   = 20
)(
    input  logic                  clk,
    input  logic                  rst_n,
    
    input  logic                  in_valid,
    input  logic [DATA_WIDTH-1:0] in_data,
    
    output logic                  out_valid,
    output logic [DATA_WIDTH-1:0] out_data
);

    // Pipeline registers for data and valid signals
    logic [DATA_WIDTH-1:0] stage_data  [0:NUM_MACS];
    logic                  stage_valid [0:NUM_MACS];

    // Seed constant for MAC operations to prevent logic optimization
    localparam logic [DATA_WIDTH-1:0] MULT_CONSTANT = 32'hA5A5_5A5A;

    // First stage driven by inputs
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stage_data[0] <= '0;
            stage_valid[0] <= 1'b0;
        end else begin
            stage_data[0] <= in_data;
            stage_valid[0] <= in_valid;
        end
    end

    // Cascaded MAC pipeline
    genvar i;
    generate
        for (i = 0; i < NUM_MACS; i++) begin : gen_mac_pipeline
            logic [DATA_WIDTH-1:0] mac_result;
            logic [DATA_WIDTH-1:0] mult_out;
            
            // Multiply-Accumulate logic
            // To ensure logic isn't completely synthesized away, 
            // we mix in the stage index and a constant.
            assign mult_out = stage_data[i] * (MULT_CONSTANT ^ i[DATA_WIDTH-1:0]);
            assign mac_result = stage_data[i] + mult_out;

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    stage_data[i+1]  <= '0;
                    stage_valid[i+1] <= 1'b0;
                end else begin
                    stage_valid[i+1] <= stage_valid[i];
                    if (stage_valid[i]) begin
                        stage_data[i+1] <= mac_result;
                    end
                end
            end
        end
    endgenerate

    // Final stage assignment
    assign out_data  = stage_data[NUM_MACS];
    assign out_valid = stage_valid[NUM_MACS];

endmodule
