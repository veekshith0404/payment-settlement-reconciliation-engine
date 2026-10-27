-- 02_reconciliation_exceptions_view.sql
-- Reconciliation rules for the payment settlement project.
-- This view reads source tables only; it does not change or insert source data.
-- Run this script in the dedicated project database after loading the fixture.
-- The as-of date is fixed so the historical synthetic fixture is reproducible.

CREATE OR REPLACE VIEW public.reconciliation_exceptions AS
WITH
evaluation_parameters (as_of_date) AS (
    VALUES (DATE '2026-10-26')
),
fee_schedule (payment_method, contracted_rate_pct) AS (
    VALUES
        ('UPI',          0.00::NUMERIC),
        ('DEBIT_CARD',   0.90::NUMERIC),
        ('CREDIT_CARD',  1.80::NUMERIC),
        ('NET_BANKING',  1.50::NUMERIC)
),

-- Successful internal orders with no matching gateway transaction.
missing_gateway AS (
    SELECT
        'MISSING_GATEWAY_RECORD'::TEXT AS defect_type,
        o.order_id::TEXT AS entity_id,
        o.amount::NUMERIC AS expected_amount,
        NULL::NUMERIC AS actual_amount,
        NULL::NUMERIC AS variance_amount,
        o.amount::NUMERIC AS amount_under_review,
        'Internal order is SUCCESS but has no matching CAPTURED gateway transaction.'::TEXT AS reason
    FROM public.internal_orders AS o
    WHERE o.internal_status = 'SUCCESS'
      AND NOT EXISTS (
          SELECT 1
          FROM public.gateway_statement AS g
          WHERE g.merchant_order_id = o.order_id
            AND g.auth_status = 'CAPTURED'
      )
),

-- Captured gateway transactions with no matching internal order.
orphan_gateway_records AS (
    SELECT
        'ORPHAN_GATEWAY_RECORD'::TEXT AS defect_type,
        g.gateway_txn_id::TEXT AS entity_id,
        g.gross_amount::NUMERIC AS expected_amount,
        NULL::NUMERIC AS actual_amount,
        NULL::NUMERIC AS variance_amount,
        g.gross_amount::NUMERIC AS amount_under_review,
        'Captured gateway transaction has no matching internal order.'::TEXT AS reason
    FROM public.gateway_statement AS g
    WHERE g.auth_status = 'CAPTURED'
      AND NOT EXISTS (
          SELECT 1
          FROM public.internal_orders AS o
          WHERE o.order_id = g.merchant_order_id
      )
),

-- An internal order marked FAILED or DROPPED even though the gateway captured payment.
internal_gateway_status_mismatches AS (
    SELECT
        'INTERNAL_GATEWAY_STATUS_MISMATCH'::TEXT AS defect_type,
        g.gateway_txn_id::TEXT AS entity_id,
        g.gross_amount::NUMERIC AS expected_amount,
        g.gross_amount::NUMERIC AS actual_amount,
        0::NUMERIC AS variance_amount,
        g.gross_amount::NUMERIC AS amount_under_review,
        ('Internal order is ' || o.internal_status || ' while the gateway transaction is CAPTURED.')::TEXT AS reason
    FROM public.internal_orders AS o
    JOIN public.gateway_statement AS g
      ON g.merchant_order_id = o.order_id
    WHERE o.internal_status IN ('FAILED', 'DROPPED')
      AND g.auth_status = 'CAPTURED'
),

-- Compare the internal order amount with the gateway's captured gross amount.
order_gateway_amount_mismatches AS (
    SELECT
        'ORDER_GATEWAY_AMOUNT_MISMATCH'::TEXT AS defect_type,
        g.gateway_txn_id::TEXT AS entity_id,
        o.amount::NUMERIC AS expected_amount,
        g.gross_amount::NUMERIC AS actual_amount,
        (g.gross_amount - o.amount)::NUMERIC AS variance_amount,
        ABS(g.gross_amount - o.amount)::NUMERIC AS amount_under_review,
        'Gateway gross amount differs from the internal order amount.'::TEXT AS reason
    FROM public.internal_orders AS o
    JOIN public.gateway_statement AS g
      ON g.merchant_order_id = o.order_id
    WHERE g.auth_status = 'CAPTURED'
      AND ABS(g.gross_amount - o.amount) >= 0.01
),

-- Calculate contracted fees independently of the rate declared by the gateway.
fee_components AS (
    SELECT
        g.gateway_txn_id,
        g.gross_amount,
        COALESCE(g.fee_deducted, 0)::NUMERIC AS actual_fee,
        COALESCE(g.gst, 0)::NUMERIC AS actual_gst,
        ROUND(g.gross_amount * fs.contracted_rate_pct / 100.0, 2)::NUMERIC AS expected_fee,
        ROUND(
            ROUND(g.gross_amount * fs.contracted_rate_pct / 100.0, 2) * 0.18,
            2
        )::NUMERIC AS expected_gst
    FROM public.gateway_statement AS g
    JOIN public.internal_orders AS o
      ON o.order_id = g.merchant_order_id
    JOIN fee_schedule AS fs
      ON fs.payment_method = o.payment_method
    WHERE g.auth_status = 'CAPTURED'
),

-- Flag an actual fee plus GST that exceeds the contracted fee plus GST.
mdr_overcharges AS (
    SELECT
        'MDR_OVERCHARGE'::TEXT AS defect_type,
        f.gateway_txn_id::TEXT AS entity_id,
        ROUND(f.expected_fee + f.expected_gst, 2)::NUMERIC AS expected_amount,
        ROUND(f.actual_fee + f.actual_gst, 2)::NUMERIC AS actual_amount,
        ROUND(
            (f.actual_fee + f.actual_gst) - (f.expected_fee + f.expected_gst),
            2
        )::NUMERIC AS variance_amount,
        ROUND(
            (f.actual_fee + f.actual_gst) - (f.expected_fee + f.expected_gst),
            2
        )::NUMERIC AS amount_under_review,
        'Actual fee plus GST exceeds the amount allowed by the contracted rate.'::TEXT AS reason
    FROM fee_components AS f
    WHERE (f.actual_fee + f.actual_gst) - (f.expected_fee + f.expected_gst) >= 0.01
),

-- Recalculate the net payout from gross amount less the recorded fee and GST.
gateway_net_payout_mismatches AS (
    SELECT
        'GATEWAY_NET_PAYOUT_MISMATCH'::TEXT AS defect_type,
        g.gateway_txn_id::TEXT AS entity_id,
        (g.gross_amount - COALESCE(g.fee_deducted, 0) - COALESCE(g.gst, 0))::NUMERIC AS expected_amount,
        g.net_payout::NUMERIC AS actual_amount,
        (g.net_payout - (g.gross_amount - COALESCE(g.fee_deducted, 0) - COALESCE(g.gst, 0)))::NUMERIC AS variance_amount,
        ABS(g.net_payout - (g.gross_amount - COALESCE(g.fee_deducted, 0) - COALESCE(g.gst, 0)))::NUMERIC AS amount_under_review,
        'Stored net payout differs from gross amount less fee and GST.'::TEXT AS reason
    FROM public.gateway_statement AS g
    WHERE g.auth_status = 'CAPTURED'
      AND ABS(
          g.net_payout - (g.gross_amount - COALESCE(g.fee_deducted, 0) - COALESCE(g.gst, 0))
      ) >= 0.01
),

-- Build expected payout totals for each captured gateway payout batch.
gateway_batches AS (
    SELECT
        g.payout_batch_id,
        SUM(g.net_payout)::NUMERIC AS expected_payout,
        (MAX(g.capture_timestamp_utc) + INTERVAL '5 hours 30 minutes')::DATE AS batch_date,
        COUNT(*)::BIGINT AS captured_transaction_count
    FROM public.gateway_statement AS g
    WHERE g.auth_status = 'CAPTURED'
      AND g.payout_batch_id IS NOT NULL
    GROUP BY g.payout_batch_id
),

-- Aggregate only bank entries whose status is CREDITED.
bank_batches AS (
    SELECT
        b.payout_batch_id,
        SUM(b.credit_amount)::NUMERIC AS actual_credit_total,
        COUNT(*)::BIGINT AS credited_entry_count,
        MAX(b.settlement_date_ist) AS last_credit_date
    FROM public.bank_statement AS b
    WHERE b.bank_status = 'CREDITED'
      AND b.payout_batch_id IS NOT NULL
    GROUP BY b.payout_batch_id
),

-- Approximate settlement deadline: the next weekday after the batch date.
-- Public holidays are not modelled in this synthetic project.
batches_with_deadline AS (
    SELECT
        gb.*,
        CASE EXTRACT(ISODOW FROM gb.batch_date)
            WHEN 5 THEN gb.batch_date + 3
            WHEN 6 THEN gb.batch_date + 2
            WHEN 7 THEN gb.batch_date + 1
            ELSE gb.batch_date + 1
        END AS settlement_due_date
    FROM gateway_batches AS gb
),

-- A credited settlement arrived later than the calculated deadline.
settlement_lags AS (
    SELECT
        'SETTLEMENT_TIMING_LAG'::TEXT AS defect_type,
        bd.payout_batch_id::TEXT AS entity_id,
        bd.expected_payout::NUMERIC AS expected_amount,
        bb.actual_credit_total::NUMERIC AS actual_amount,
        (bb.actual_credit_total - bd.expected_payout)::NUMERIC AS variance_amount,
        bd.expected_payout::NUMERIC AS amount_under_review,
        'Last credited bank entry arrived after the settlement deadline.'::TEXT AS reason
    FROM batches_with_deadline AS bd
    JOIN bank_batches AS bb
      ON bb.payout_batch_id = bd.payout_batch_id
    WHERE bb.last_credit_date > bd.settlement_due_date
),

-- Multiple credited entries are a duplicate only when their total exceeds the
-- expected payout. Legitimate split credits that add up to the expected total
-- are not duplicates.
duplicate_bank_credits AS (
    SELECT
        'DUPLICATE_BANK_CREDIT'::TEXT AS defect_type,
        bd.payout_batch_id::TEXT AS entity_id,
        bd.expected_payout::NUMERIC AS expected_amount,
        bb.actual_credit_total::NUMERIC AS actual_amount,
        (bb.actual_credit_total - bd.expected_payout)::NUMERIC AS variance_amount,
        (bb.actual_credit_total - bd.expected_payout)::NUMERIC AS amount_under_review,
        'Multiple credited bank entries exceed the expected payout for the batch.'::TEXT AS reason
    FROM batches_with_deadline AS bd
    JOIN bank_batches AS bb
      ON bb.payout_batch_id = bd.payout_batch_id
    WHERE bb.credited_entry_count > 1
      AND bb.actual_credit_total >= bd.expected_payout + 0.01
),

-- Catch credited short/excess totals, excluding over-credits already classified
-- as duplicate bank credits.
bank_settlement_amount_mismatches AS (
    SELECT
        'BANK_SETTLEMENT_AMOUNT_MISMATCH'::TEXT AS defect_type,
        bd.payout_batch_id::TEXT AS entity_id,
        bd.expected_payout::NUMERIC AS expected_amount,
        bb.actual_credit_total::NUMERIC AS actual_amount,
        (bb.actual_credit_total - bd.expected_payout)::NUMERIC AS variance_amount,
        ABS(bb.actual_credit_total - bd.expected_payout)::NUMERIC AS amount_under_review,
        'Credited bank total is short or excessive versus the expected payout.'::TEXT AS reason
    FROM batches_with_deadline AS bd
    JOIN bank_batches AS bb
      ON bb.payout_batch_id = bd.payout_batch_id
    WHERE ABS(bb.actual_credit_total - bd.expected_payout) >= 0.01
      AND NOT (
          bb.credited_entry_count > 1
          AND bb.actual_credit_total >= bd.expected_payout + 0.01
      )
),

-- Report each non-credited bank entry separately instead of mislabelling the
-- same payout batch as a missing settlement.
non_credited_bank_entries AS (
    SELECT
        'NON_CREDITED_BANK_ENTRY'::TEXT AS defect_type,
        b.bank_entry_id::TEXT AS entity_id,
        COALESCE(gb.expected_payout, b.credit_amount)::NUMERIC AS expected_amount,
        b.credit_amount::NUMERIC AS actual_amount,
        (b.credit_amount - COALESCE(gb.expected_payout, b.credit_amount))::NUMERIC AS variance_amount,
        COALESCE(gb.expected_payout, b.credit_amount)::NUMERIC AS amount_under_review,
        ('Bank entry has status ' || COALESCE(b.bank_status, 'NULL') || ', not CREDITED.')::TEXT AS reason
    FROM public.bank_statement AS b
    LEFT JOIN gateway_batches AS gb
      ON gb.payout_batch_id = b.payout_batch_id
    WHERE b.bank_status IS DISTINCT FROM 'CREDITED'
),

-- A gateway batch is missing settlement only if the deadline has passed and
-- there is no credited bank entry and no non-credited bank entry for that batch.
missing_bank_settlements AS (
    SELECT
        'MISSING_BANK_SETTLEMENT'::TEXT AS defect_type,
        bd.payout_batch_id::TEXT AS entity_id,
        bd.expected_payout::NUMERIC AS expected_amount,
        NULL::NUMERIC AS actual_amount,
        NULL::NUMERIC AS variance_amount,
        bd.expected_payout::NUMERIC AS amount_under_review,
        'Gateway payout batch has no bank entry of any status after its settlement deadline.'::TEXT AS reason
    FROM batches_with_deadline AS bd
    WHERE bd.settlement_due_date < (SELECT as_of_date FROM evaluation_parameters)
      AND NOT EXISTS (
          SELECT 1
          FROM public.bank_statement AS b
          WHERE b.payout_batch_id = bd.payout_batch_id
      )
),

-- Credited bank batches with no corresponding captured gateway payout.
orphan_bank_credits AS (
    SELECT
        'ORPHAN_BANK_CREDIT'::TEXT AS defect_type,
        bb.payout_batch_id::TEXT AS entity_id,
        bb.actual_credit_total::NUMERIC AS expected_amount,
        bb.actual_credit_total::NUMERIC AS actual_amount,
        0::NUMERIC AS variance_amount,
        bb.actual_credit_total::NUMERIC AS amount_under_review,
        'Credited bank batch has no matching captured gateway payout.'::TEXT AS reason
    FROM bank_batches AS bb
    LEFT JOIN gateway_batches AS gb
      ON gb.payout_batch_id = bb.payout_batch_id
    WHERE gb.payout_batch_id IS NULL
)

SELECT * FROM missing_gateway
UNION ALL SELECT * FROM orphan_gateway_records
UNION ALL SELECT * FROM internal_gateway_status_mismatches
UNION ALL SELECT * FROM order_gateway_amount_mismatches
UNION ALL SELECT * FROM mdr_overcharges
UNION ALL SELECT * FROM gateway_net_payout_mismatches
UNION ALL SELECT * FROM settlement_lags
UNION ALL SELECT * FROM duplicate_bank_credits
UNION ALL SELECT * FROM bank_settlement_amount_mismatches
UNION ALL SELECT * FROM non_credited_bank_entries
UNION ALL SELECT * FROM missing_bank_settlements
UNION ALL SELECT * FROM orphan_bank_credits;
