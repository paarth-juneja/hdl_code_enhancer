// Five-domain qualification wrapper around the unmodified OpenCores ethmac.

`default_nettype none

module nebula_ethmac5_top (
    input  wire        wb_clk_i,
    input  wire        mtx_clk_pad_i,
    input  wire        mrx_clk_pad_i,
    input  wire        aux0_clk_i,
    input  wire        aux1_clk_i,
    input  wire        wb_rst_i,

    input  wire [31:0] wb_dat_i,
    output wire [31:0] wb_dat_o,
    input  wire  [9:0] wb_adr_i,
    input  wire  [3:0] wb_sel_i,
    input  wire        wb_we_i,
    input  wire        wb_cyc_i,
    input  wire        wb_stb_i,
    output wire        wb_ack_o,
    output wire        wb_err_o,

    output wire [31:0] m_wb_adr_o,
    output wire  [3:0] m_wb_sel_o,
    output wire        m_wb_we_o,
    output wire [31:0] m_wb_dat_o,
    input  wire [31:0] m_wb_dat_i,
    output wire        m_wb_cyc_o,
    output wire        m_wb_stb_o,
    input  wire        m_wb_ack_i,
    input  wire        m_wb_err_i,
    output wire  [2:0] m_wb_cti_o,
    output wire  [1:0] m_wb_bte_o,

    output wire  [3:0] mtxd_pad_o,
    output wire        mtxen_pad_o,
    output wire        mtxerr_pad_o,
    input  wire  [3:0] mrxd_pad_i,
    input  wire        mrxdv_pad_i,
    input  wire        mrxerr_pad_i,
    input  wire        mcoll_pad_i,
    input  wire        mcrs_pad_i,
    output wire        mdc_pad_o,
    input  wire        md_pad_i,
    output wire        md_pad_o,
    output wire        md_padoe_o,
    output wire        int_o,

    input  wire        aux_command_toggle_i,
    input  wire [31:0] aux0_seed_i,
    input  wire [31:0] aux1_seed_i,
    output wire [31:0] aux0_digest_o,
    output wire [31:0] aux1_digest_o,
    output wire  [1:0] aux_response_o,

    output wire wb_clk_div2_o,
    output wire tx_clk_div2_o,
    output wire rx_clk_div2_o,
    output wire aux0_clk_div2_o,
    output wire aux1_clk_div2_o,
    output wire [79:0] generated_activity_o
);
    wire aux0_response_async;
    wire aux1_response_async;
    wire aux0_load;
    wire aux1_load;
    reg  aux0_response_meta;
    reg  aux0_response_sync;
    reg  aux1_response_meta;
    reg  aux1_response_sync;

    reg [15:0] wb_generated_activity;
    reg [15:0] tx_generated_activity;
    reg [15:0] rx_generated_activity;
    reg [15:0] aux0_generated_activity;
    reg [15:0] aux1_generated_activity;

    ethmac u_ethmac (
        .wb_clk_i(wb_clk_i), .wb_rst_i(wb_rst_i),
        .wb_dat_i(wb_dat_i), .wb_dat_o(wb_dat_o),
        .wb_adr_i(wb_adr_i), .wb_sel_i(wb_sel_i), .wb_we_i(wb_we_i),
        .wb_cyc_i(wb_cyc_i), .wb_stb_i(wb_stb_i),
        .wb_ack_o(wb_ack_o), .wb_err_o(wb_err_o),
        .m_wb_adr_o(m_wb_adr_o), .m_wb_sel_o(m_wb_sel_o),
        .m_wb_we_o(m_wb_we_o), .m_wb_dat_o(m_wb_dat_o),
        .m_wb_dat_i(m_wb_dat_i), .m_wb_cyc_o(m_wb_cyc_o),
        .m_wb_stb_o(m_wb_stb_o), .m_wb_ack_i(m_wb_ack_i),
        .m_wb_err_i(m_wb_err_i), .m_wb_cti_o(m_wb_cti_o),
        .m_wb_bte_o(m_wb_bte_o),
        .mtx_clk_pad_i(mtx_clk_pad_i), .mtxd_pad_o(mtxd_pad_o),
        .mtxen_pad_o(mtxen_pad_o), .mtxerr_pad_o(mtxerr_pad_o),
        .mrx_clk_pad_i(mrx_clk_pad_i), .mrxd_pad_i(mrxd_pad_i),
        .mrxdv_pad_i(mrxdv_pad_i), .mrxerr_pad_i(mrxerr_pad_i),
        .mcoll_pad_i(mcoll_pad_i), .mcrs_pad_i(mcrs_pad_i),
        .mdc_pad_o(mdc_pad_o), .md_pad_i(md_pad_i),
        .md_pad_o(md_pad_o), .md_padoe_o(md_padoe_o), .int_o(int_o)
    );

    nebula_clock_div2 u_wb_div  (.clk_in(wb_clk_i),      .reset(wb_rst_i), .clk_out(wb_clk_div2_o));
    nebula_clock_div2 u_tx_div  (.clk_in(mtx_clk_pad_i), .reset(wb_rst_i), .clk_out(tx_clk_div2_o));
    nebula_clock_div2 u_rx_div  (.clk_in(mrx_clk_pad_i), .reset(wb_rst_i), .clk_out(rx_clk_div2_o));
    nebula_clock_div2 u_aux0_div(.clk_in(aux0_clk_i),    .reset(wb_rst_i), .clk_out(aux0_clk_div2_o));
    nebula_clock_div2 u_aux1_div(.clk_in(aux1_clk_i),    .reset(wb_rst_i), .clk_out(aux1_clk_div2_o));

    nebula_aux_cdc u_aux0_cdc (
        .clk(aux0_clk_i), .reset(wb_rst_i),
        .command_toggle_async(aux_command_toggle_i),
        .command_pulse(aux0_load), .response_toggle(aux0_response_async)
    );
    nebula_aux_cdc u_aux1_cdc (
        .clk(aux1_clk_i), .reset(wb_rst_i),
        .command_toggle_async(aux_command_toggle_i),
        .command_pulse(aux1_load), .response_toggle(aux1_response_async)
    );
    nebula_aux_domain u_aux0 (
        .clk(aux0_clk_i), .reset(wb_rst_i), .load(aux0_load),
        .seed(aux0_seed_i), .digest(aux0_digest_o)
    );
    nebula_aux_domain u_aux1 (
        .clk(aux1_clk_i), .reset(wb_rst_i), .load(aux1_load),
        .seed(aux1_seed_i), .digest(aux1_digest_o)
    );

    // Return-path synchronizers terminate both auxiliary CDC handshakes in WB.
    always @(posedge wb_clk_i or posedge wb_rst_i) begin
        if (wb_rst_i) begin
            aux0_response_meta <= 1'b0;
            aux0_response_sync <= 1'b0;
            aux1_response_meta <= 1'b0;
            aux1_response_sync <= 1'b0;
        end else begin
            aux0_response_meta <= aux0_response_async;
            aux0_response_sync <= aux0_response_meta;
            aux1_response_meta <= aux1_response_async;
            aux1_response_sync <= aux1_response_meta;
        end
    end

    // Give every declared generated clock observable sequential endpoints.
    always @(posedge wb_clk_div2_o or posedge wb_rst_i)
        if (wb_rst_i) wb_generated_activity <= 16'b0;
        else wb_generated_activity <= wb_generated_activity + 1'b1;
    always @(posedge tx_clk_div2_o or posedge wb_rst_i)
        if (wb_rst_i) tx_generated_activity <= 16'b0;
        else tx_generated_activity <= tx_generated_activity + 1'b1;
    always @(posedge rx_clk_div2_o or posedge wb_rst_i)
        if (wb_rst_i) rx_generated_activity <= 16'b0;
        else rx_generated_activity <= rx_generated_activity + 1'b1;
    always @(posedge aux0_clk_div2_o or posedge wb_rst_i)
        if (wb_rst_i) aux0_generated_activity <= 16'b0;
        else aux0_generated_activity <= aux0_generated_activity + 1'b1;
    always @(posedge aux1_clk_div2_o or posedge wb_rst_i)
        if (wb_rst_i) aux1_generated_activity <= 16'b0;
        else aux1_generated_activity <= aux1_generated_activity + 1'b1;

    assign aux_response_o = {aux1_response_sync, aux0_response_sync};
    assign generated_activity_o = {
        aux1_generated_activity, aux0_generated_activity,
        rx_generated_activity, tx_generated_activity, wb_generated_activity
    };
endmodule

`default_nettype wire
