-- =============================================================================
-- CORE.Stg_DCE_OpenInvoiceAudit
-- One row per charge line on any non-posted (status != 'P') invoice.
-- Pre-joined: invoice → charge → chargeback → contract → customer
--             + order (LEFT) + order_detail aggregated (LEFT)
--             + contracted rate with precedence resolution (LEFT)
-- Computed:   expected_amount, discrepancy, flags
-- Refreshed:  nightly via CORE.usp_Refresh_DCE_OpenInvoiceAudit
-- =============================================================================

IF OBJECT_ID('CORE.Stg_DCE_OpenInvoiceAudit', 'U') IS NOT NULL
    DROP TABLE CORE.Stg_DCE_OpenInvoiceAudit;

CREATE TABLE CORE.Stg_DCE_OpenInvoiceAudit
(
    -- ── Invoice ──────────────────────────────────────────────────────────────
    invoice_id                      INT,
    invoice_number                  NVARCHAR(20),
    invoice_status                  NVARCHAR(1),        -- 'G'=Generated, 'A'=Approved
    invoice_generated_date          DATETIME2(7),
    invoice_approved_date           DATETIME2(7),
    invoice_contract_type_code      NVARCHAR(255),      -- e.g. 'Group 1', 'Group 3'

    -- ── Charge ───────────────────────────────────────────────────────────────
    charge_id                       INT,
    charge_amount                   FLOAT,              -- actual billed amount
    charge_date                     DATETIME,
    order_num_value                 NVARCHAR(255),      -- order number on the charge
    billed_rate                     FLOAT,              -- c.rate: rate Korber applied
    billed_per_text                 NVARCHAR(255),      -- unit (EA, CWT, etc.)
    billed_qty_raw                  NVARCHAR(255),      -- prompt_text_value as-is
    billed_qty                      FLOAT,              -- TRY_CAST; NULL = manual/blank

    -- ── Chargeback / contract ─────────────────────────────────────────────
    chargeback_id                   INT,
    chargeback_code                 NVARCHAR(255),
    chargeback_description          NVARCHAR(255),
    chargeback_type                 NVARCHAR(255),      -- WMS Event | Manual - Adhoc | Renewal - UOM in Storage | etc.
    contract_invoice_type_code      NVARCHAR(255),
    gl_code_description             NVARCHAR(255),

    -- ── Customer / warehouse ─────────────────────────────────────────────
    customer_id                     INT,
    customer_code                   NVARCHAR(30),
    customer_name                   NVARCHAR(255),
    wh_id                           NVARCHAR(20),

    -- ── Order (LEFT — some charges have no linked order) ─────────────────
    order_id                        INT,
    display_order_number            NVARCHAR(255),
    order_status                    NVARCHAR(50),
    order_type_id                   INT,                -- no name table exists; prefix inferred
    actual_ship_date                DATETIME,
    bol_number                      NVARCHAR(255),
    carrier                         NVARCHAR(255),
    store_order_number              NVARCHAR(255),
    cust_po_number                  NVARCHAR(255),

    -- ── Order detail — aggregated to one row per order (LEFT) ─────────────
    source_vessel                   NVARCHAR(255),
    dest_vessel                     NVARCHAR(255),
    item_description                NVARCHAR(255),
    lot_number                      NVARCHAR(255),

    -- ── Contracted rate — precedence-resolved from CORE.Core_Rates ────────
    contracted_rate                 FLOAT,              -- NULL = no rate match found
    contracted_per_text             NVARCHAR(255),
    contracted_order_type           NVARCHAR(255),      -- rule that matched (for audit trail)
    contracted_container_type       NVARCHAR(255),
    contracted_precedence           INT,
    rate_source                     NVARCHAR(20),       -- 'WMS_Rates' | 'WMS_Manual' | NULL
    rate_match_found                BIT NOT NULL DEFAULT 0,

    -- ── Audit computed ────────────────────────────────────────────────────
    -- expected_amount: NULL when billed_qty is blank (manual/flat charge)
    --                  or when no rate match exists
    expected_amount                 FLOAT,
    discrepancy                     FLOAT,              -- charge_amount - expected_amount; NULL if expected is NULL
    rate_variance                   FLOAT,              -- billed_rate - contracted_rate; NULL if no match
    is_manual_charge                BIT NOT NULL DEFAULT 0,   -- 1 = blank/null prompt_text_value
    has_discrepancy                 BIT NOT NULL DEFAULT 0,   -- 1 = ABS(discrepancy) > 0.01

    -- ── ETL ──────────────────────────────────────────────────────────────
    ETL_LoadDate                    DATETIME NOT NULL DEFAULT '1900-01-01'  -- overwritten at INSERT time
)
WITH (
    CLUSTERED COLUMNSTORE INDEX,
    DISTRIBUTION = HASH(customer_code)
);
