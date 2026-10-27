-- ============================================================
-- PAYMENT SETTLEMENT RECONCILIATION ENGINE
-- 01_create_tables.sql | PostgreSQL 18
--
-- Run in the intended dedicated project database.
-- Safe for setup: uses CREATE TABLE IF NOT EXISTS and never drops objects.
-- The script also adds a check constraint requiring a timestamp for CAPTURED
-- gateway rows. Existing data that violates the constraint must be corrected.
-- Existing table columns are not altered.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.internal_orders (
    order_id VARCHAR(32) PRIMARY KEY,
    order_timestamp_utc TIMESTAMP NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    payment_method VARCHAR(16) NOT NULL CHECK (
        payment_method IN ('UPI', 'DEBIT_CARD', 'CREDIT_CARD', 'NET_BANKING')
    ),
    internal_status VARCHAR(16) NOT NULL CHECK (
        internal_status IN ('SUCCESS', 'FAILED', 'DROPPED')
    )
);

CREATE TABLE IF NOT EXISTS public.gateway_statement (
    gateway_txn_id VARCHAR(36) PRIMARY KEY,
    merchant_order_id VARCHAR(32) NOT NULL,
    auth_status VARCHAR(16) NOT NULL,
    capture_timestamp_utc TIMESTAMP,
    gross_amount NUMERIC(12, 2) NOT NULL,
    mdr_rate_pct NUMERIC(5, 2) NOT NULL,
    fee_deducted NUMERIC(10, 2) NOT NULL,
    gst NUMERIC(10, 2) NOT NULL,
    net_payout NUMERIC(12, 2) NOT NULL,
    payout_batch_id VARCHAR(40) NOT NULL
);

-- A captured gateway transaction must have a capture timestamp because
-- settlement deadlines are derived from this timestamp. Non-captured rows may
-- legitimately have a NULL capture timestamp.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_gateway_captured_timestamp_present'
          AND conrelid = 'public.gateway_statement'::regclass
    ) THEN
        ALTER TABLE public.gateway_statement
        ADD CONSTRAINT chk_gateway_captured_timestamp_present
        CHECK (
            auth_status <> 'CAPTURED'
            OR capture_timestamp_utc IS NOT NULL
        );
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.bank_statement (
    bank_entry_id VARCHAR(60) PRIMARY KEY,
    payout_batch_id VARCHAR(40) NOT NULL,
    credit_amount NUMERIC(14, 2) NOT NULL,
    settlement_date_ist DATE NOT NULL,
    bank_status VARCHAR(16) NOT NULL
);

CREATE TABLE IF NOT EXISTS public.ground_truth_exceptions (
    entity_type VARCHAR(32) NOT NULL,
    entity_id VARCHAR(60) NOT NULL,
    defect_type VARCHAR(64) NOT NULL,
    expected_amount NUMERIC(12, 2) NOT NULL,
    impact_basis VARCHAR(64) NOT NULL,
    description TEXT NOT NULL,
    PRIMARY KEY (defect_type, entity_id)
);
