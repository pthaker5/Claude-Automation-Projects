-- =============================================================================
-- CORE.usp_Refresh_DCE_OpenInvoiceAudit
--
-- Full refresh of CORE.Stg_DCE_OpenInvoiceAudit.
-- Runs nightly via ADF; also callable on-demand.
--
-- Rate sources (replaces CORE.Core_Rates):
--   WMS_Rates   — Korber.t_bmm_chargeback_rate
--                 Active rates only (rate_status='A', contract/chargeback status='A')
--                 Supports container_type + precedence matching
--   WMS_Manual  — Korber.t_bmm_param_manual_csr_prompt / t_bmm_param_manual_prompt
--                 Manual-Prompted and Manual-CSR-Prompted charge types only
--                 No container_type restriction (applies to all)
--
-- Rate resolution per charge:
--   1. Union both sources into #ContractedRates (keyed on chargeback_id)
--   2. Join on chargeback_id; filter container_type to exact match or wildcard
--      NULL/empty source_vessel treated as wildcard (no order context available)
--   3. ROW_NUMBER() per charge_id: exact container match beats wildcard, then lowest precedence
--   4. Keep rate_rank = 1 only — one contracted rate row per charge
--
-- OUT OF SCOPE (flagged, not audited by this proc):
--   Renewal - UOM in Storage      }  Snapshot-based billing model — qty comes from
--   Renewal - UOM Anniversary Date}  inventory snapshot, not prompt_text_value.
--   Inbound Storage (no order)    }  These require the pull_recurring_storage audit path.
--   These rows are included with rate_match_found=0 and rate_source='Renewal_Review'.
--
-- Closed = Posted (status = 'P'). This proc excludes all posted invoices.
-- =============================================================================

IF OBJECT_ID('CORE.usp_Refresh_DCE_OpenInvoiceAudit', 'P') IS NOT NULL
    DROP PROCEDURE CORE.usp_Refresh_DCE_OpenInvoiceAudit;
GO

CREATE PROCEDURE CORE.usp_Refresh_DCE_OpenInvoiceAudit
AS
BEGIN
    SET NOCOUNT ON;

    -- ── Step 1: Aggregate order_detail to one row per order ──────────────────
    -- Avoids fan-out when an order has multiple detail lines.
    -- Scoped to orders that appear on open invoices only.
    IF OBJECT_ID('tempdb..#OrderDetail') IS NOT NULL DROP TABLE #OrderDetail;

    SELECT
        od.order_id,
        MIN(od.source_vessel)    AS source_vessel,
        MIN(od.dest_vessel)      AS dest_vessel,
        MIN(od.item_description) AS item_description,
        MIN(od.lot_number)       AS lot_number
    INTO #OrderDetail
    FROM Korber.t_order_detail od
    WHERE od.order_id IN (
        SELECT DISTINCT o.order_id
        FROM Korber.t_bmm_invoice inv
        JOIN Korber.t_bmm_charge c ON c.invoice_id  = inv.invoice_id
        JOIN Korber.t_order o      ON o.display_order_number = c.order_num_value
        WHERE inv.status NOT IN ('P')
          AND c.charge_amount <> 0
    )
    GROUP BY od.order_id;

    -- ── Step 2: Union both rate sources into a single temp table ─────────────
    -- Mirrors the two existing rate queries exactly, adapted for EDW schema prefix.
    -- AAD.dbo tier lookups omitted — display-only, not needed for audit math.
    IF OBJECT_ID('tempdb..#ContractedRates') IS NOT NULL DROP TABLE #ContractedRates;

    -- WMS Rates: event-based charges with container_type / precedence
    SELECT
        chrg.chargeback_id,
        CAST(cr.rate AS FLOAT)                  AS contracted_rate,
        cr.per_text                             AS contracted_per_text,
        ISNULL(cr.order_type, '<ANY>')          AS contracted_order_type,
        ISNULL(cr.container_type, '<ANY>')      AS contracted_container_type,
        ISNULL(cr.dest_container_type, '<ANY>') AS contracted_dest_container_type,
        cr.precedence                           AS contracted_precedence,
        'WMS_Rates'                             AS rate_source
    INTO #ContractedRates
    FROM Korber.t_bmm_customer cm
    JOIN Korber.t_bmm_contract_master com
        ON  com.customer_id = cm.customer_id
    JOIN Korber.t_bmm_contract_invoice_type cit
        ON  cit.contract_id = com.contract_id
    JOIN Korber.t_bmm_cont_inv_type_chargeback chrg
        ON  chrg.contract_invoice_type_id = cit.contract_invoice_type_id
    JOIN Korber.t_bmm_chargeback_type ct
        ON  ct.chargeback_type_id = chrg.chargeback_type_id
    JOIN Korber.t_bmm_chargeback_rate cr
        ON  cr.chargeback_id = chrg.chargeback_id
    WHERE com.status   = 'A'
      AND cit.status   = 'A'
      AND chrg.status  = 'A'
      AND cr.rate_status = 'A'

    UNION ALL

    -- WMS Manual Rates: Manual-Prompted and Manual-CSR-Prompted
    -- Rate from t_bmm_param_manual_csr_prompt preferred over t_bmm_param_manual_prompt
    SELECT
        ISNULL(mca.chargeback_id, mp.chargeback_id) AS chargeback_id,
        CAST(ISNULL(mca.rate, mp.rate) AS FLOAT)    AS contracted_rate,
        NULL                                         AS contracted_per_text,
        'All'                                        AS contracted_order_type,
        'All'                                        AS contracted_container_type,
        'All'                                        AS contracted_dest_container_type,
        NULL                                         AS contracted_precedence,
        'WMS_Manual'                                 AS rate_source
    FROM Korber.t_bmm_contract_master cm
    JOIN Korber.t_bmm_customer cust
        ON  cust.customer_id = cm.customer_id
    JOIN Korber.t_bmm_contract_invoice_type cit
        ON  cm.contract_id = cit.contract_id
    JOIN Korber.t_bmm_cont_inv_type_chargeback chrg
        ON  chrg.contract_invoice_type_id = cit.contract_invoice_type_id
    JOIN Korber.t_bmm_chargeback_type chtp
        ON  chtp.chargeback_type_id = chrg.chargeback_type_id
    LEFT JOIN Korber.t_bmm_param_manual_csr_prompt mca
        ON  mca.chargeback_id = chrg.chargeback_id
    LEFT JOIN Korber.t_bmm_param_manual_prompt mp
        ON  mp.chargeback_id = chrg.chargeback_id
    WHERE chtp.chargeback_type IN ('Manual - Prompted', 'Manual - CSR Prompted')
      AND chrg.status = 'A'
      AND cm.status   = 'A'
      AND ISNULL(mca.rate, mp.rate) IS NOT NULL;

    -- ── Step 3: Build charge base with ALL matching rate candidates ───────────
    IF OBJECT_ID('tempdb..#ChargeRanked') IS NOT NULL DROP TABLE #ChargeRanked;

    SELECT
        -- Invoice
        inv.invoice_id,
        inv.invoice_number,
        inv.status                              AS invoice_status,
        inv.generated_date                      AS invoice_generated_date,
        inv.approved_date                       AS invoice_approved_date,
        cit.contract_invoice_type_code          AS invoice_contract_type_code,

        -- Charge
        c.charge_id,
        CAST(c.charge_amount AS FLOAT)          AS charge_amount,
        c.charge_date_time                      AS charge_date,
        c.order_num_value,
        CAST(c.rate AS FLOAT)                   AS billed_rate,
        cr_billed.per_text                      AS billed_per_text,
        c.prompt_text_value                     AS billed_qty_raw,
        TRY_CAST(
            NULLIF(LTRIM(RTRIM(c.prompt_text_value)), '')
            AS FLOAT
        )                                       AS billed_qty,

        -- Chargeback / contract
        cb.chargeback_id,
        cb.chargeback_code,
        cb.description                          AS chargeback_description,
        cit.contract_invoice_type_code,
        gl.description                          AS gl_code_description,
        chtp.chargeback_type,

        -- Customer / warehouse
        cust.customer_id,
        cust.customer_code,
        cust.customer_name,
        cm.wh_id,

        -- Order (LEFT)
        o.order_id,
        o.display_order_number,
        o.status                                AS order_status,
        o.type_id                               AS order_type_id,
        o.actual_ship_date,
        o.bol_number,
        o.carrier,
        o.store_order_number,
        o.cust_po_number,

        -- Order detail aggregated (LEFT)
        od.source_vessel,
        od.dest_vessel,
        od.item_description,
        od.lot_number,

        -- Contracted rate columns (NULL when no match)
        r.contracted_rate,
        r.contracted_per_text,
        r.contracted_order_type,
        r.contracted_container_type,
        r.contracted_precedence,
        r.rate_source,

        -- Rate ranking per charge: exact container match > wildcard, then lowest precedence.
        -- When source_vessel is NULL/empty, all candidates rank equally on container;
        -- precedence and rate_source tiebreak still apply.
        ROW_NUMBER() OVER (
            PARTITION BY c.charge_id
            ORDER BY
                CASE
                    WHEN NULLIF(od.source_vessel,'') IS NULL               THEN 2  -- no context, treat as wildcard
                    WHEN r.contracted_container_type IN ('<ANY>', 'All')   THEN 2
                    WHEN r.contracted_container_type = od.source_vessel    THEN 1
                    ELSE 2
                END,
                ISNULL(r.contracted_precedence, 9999),
                CASE WHEN r.rate_source = 'WMS_Rates' THEN 1 ELSE 2 END
        )                                       AS rate_rank

    INTO #ChargeRanked
    FROM Korber.t_bmm_invoice inv
    JOIN Korber.t_bmm_charge c
        ON  c.invoice_id     = inv.invoice_id
        AND c.charge_amount <> 0
    JOIN Korber.t_bmm_cont_inv_type_chargeback cb
        ON  cb.chargeback_id = c.chargeback_id
    JOIN Korber.t_bmm_contract_invoice_type cit
        ON  cit.contract_invoice_type_id = cb.contract_invoice_type_id
    JOIN Korber.t_bmm_contract_master cm
        ON  cm.contract_id   = cit.contract_id
    JOIN Korber.t_bmm_customer cust
        ON  cust.customer_id = cm.customer_id
    -- GL code lives on t_bmm_cont_inv_type_chargeback, confirmed from WMS Rates query
    LEFT JOIN Korber.t_bmm_gl_code gl
        ON  gl.gl_code_id    = cb.gl_code_id
    JOIN Korber.t_bmm_chargeback_type chtp
        ON  chtp.chargeback_type_id = cb.chargeback_type_id
    -- Billed rate row (for per_text on the actual applied rate)
    LEFT JOIN Korber.t_bmm_chargeback_rate cr_billed
        ON  cr_billed.chargeback_rate_id = c.chargeback_rate_id
    -- Order context
    LEFT JOIN Korber.t_order o
        ON  o.display_order_number = c.order_num_value
    LEFT JOIN #OrderDetail od
        ON  od.order_id      = o.order_id
    -- Contracted rate: both sources, container_type wildcard-expanded.
    -- NULL or empty source_vessel (no order detail context) treated as wildcard:
    -- allow any rate to match and let precedence pick the best one.
    LEFT JOIN #ContractedRates r
        ON  r.chargeback_id  = c.chargeback_id
        AND (
            r.contracted_container_type IN ('<ANY>', 'All')
            OR r.contracted_container_type = od.source_vessel
            OR NULLIF(od.source_vessel, '') IS NULL  -- no vessel context: match all candidates
        )
    WHERE inv.status NOT IN ('P');

    -- ── Step 4: Insert best-ranked rate row per charge ────────────────────────
    TRUNCATE TABLE CORE.Stg_DCE_OpenInvoiceAudit;

    INSERT INTO CORE.Stg_DCE_OpenInvoiceAudit (
        invoice_id, invoice_number, invoice_status,
        invoice_generated_date, invoice_approved_date, invoice_contract_type_code,
        charge_id, charge_amount, charge_date, order_num_value,
        billed_rate, billed_per_text, billed_qty_raw, billed_qty,
        chargeback_id, chargeback_code, chargeback_description, chargeback_type,
        contract_invoice_type_code, gl_code_description,
        customer_id, customer_code, customer_name, wh_id,
        order_id, display_order_number, order_status, order_type_id,
        actual_ship_date, bol_number, carrier, store_order_number, cust_po_number,
        source_vessel, dest_vessel, item_description, lot_number,
        contracted_rate, contracted_per_text, contracted_order_type,
        contracted_container_type, contracted_precedence,
        rate_source, rate_match_found,
        expected_amount, discrepancy, rate_variance,
        is_manual_charge, has_discrepancy,
        ETL_LoadDate
    )
    SELECT
        invoice_id, invoice_number, invoice_status,
        invoice_generated_date, invoice_approved_date, invoice_contract_type_code,
        charge_id, charge_amount, charge_date, order_num_value,
        billed_rate, billed_per_text, billed_qty_raw, billed_qty,
        chargeback_id, chargeback_code, chargeback_description, chargeback_type,
        contract_invoice_type_code, gl_code_description,
        customer_id, customer_code, customer_name, wh_id,
        order_id, display_order_number, order_status, order_type_id,
        actual_ship_date, bol_number, carrier, store_order_number, cust_po_number,
        source_vessel, dest_vessel, item_description, lot_number,

        -- Rate
        contracted_rate,
        contracted_per_text,
        contracted_order_type,
        contracted_container_type,
        contracted_precedence,
        -- Reclassify Renewal/Storage/Inbound types with no order as 'Renewal_Review':
        -- these require snapshot-based audit (out of scope for this table).
        CASE
            WHEN contracted_rate IS NULL
             AND chargeback_type IN (
                 'Renewal - UOM in Storage', 'Renewal - UOM Anniversary Date',
                 'Inbound Storage', 'Recurring'
             ) THEN 'Renewal_Review'
            ELSE rate_source
        END,
        CASE WHEN contracted_rate IS NOT NULL THEN 1 ELSE 0 END,

        -- expected_amount: NULL when qty is blank (manual charge) or no rate match found
        CASE
            WHEN billed_qty      IS NULL THEN NULL
            WHEN contracted_rate IS NULL THEN NULL
            ELSE billed_qty * contracted_rate
        END,

        -- discrepancy: positive = overbilled, negative = underbilled
        CASE
            WHEN billed_qty      IS NULL THEN NULL
            WHEN contracted_rate IS NULL THEN NULL
            ELSE charge_amount - (billed_qty * contracted_rate)
        END,

        -- rate_variance: difference between the rate Korber applied vs contracted rate
        CASE
            WHEN contracted_rate IS NULL THEN NULL
            ELSE billed_rate - contracted_rate
        END,

        -- is_manual_charge: blank prompt_text_value — qty unknown, can't auto-audit
        CASE WHEN billed_qty IS NULL THEN 1 ELSE 0 END,

        -- has_discrepancy: calculable and meaningful difference > $0.01
        CASE
            WHEN billed_qty IS NULL OR contracted_rate IS NULL THEN 0
            WHEN ABS(charge_amount - (billed_qty * contracted_rate)) > 0.01 THEN 1
            ELSE 0
        END,

        GETUTCDATE()

    FROM #ChargeRanked
    WHERE rate_rank = 1;

    -- Cleanup
    DROP TABLE #OrderDetail;
    DROP TABLE #ContractedRates;
    DROP TABLE #ChargeRanked;

END
GO
