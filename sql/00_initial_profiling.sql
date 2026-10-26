-- 00_initial_profiling.sql
-- Run after the four CSV files have been imported.

-- 1. Check the number of rows in each table.
SELECT 'internal_orders' AS table_name, COUNT(*) AS row_count
FROM public.internal_orders

UNION ALL

SELECT 'gateway_statement', COUNT(*)
FROM public.gateway_statement

UNION ALL

SELECT 'bank_statement', COUNT(*)
FROM public.bank_statement

UNION ALL

SELECT 'ground_truth_exceptions', COUNT(*)
FROM public.ground_truth_exceptions

ORDER BY table_name;


-- 2. Check the status of internal orders.
SELECT
    internal_status,
    COUNT(*) AS order_count
FROM public.internal_orders
GROUP BY internal_status
ORDER BY order_count DESC;


-- 3. Check the status of gateway transactions.
SELECT
    auth_status,
    COUNT(*) AS transaction_count
FROM public.gateway_statement
GROUP BY auth_status
ORDER BY transaction_count DESC;


-- 4. Summarize bank entries and credited amounts.
SELECT
    bank_status,
    COUNT(*) AS entry_count,
    SUM(credit_amount) AS total_credit_amount
FROM public.bank_statement
GROUP BY bank_status
ORDER BY bank_status;


-- 5. Summarize the expected exceptions used for testing.
-- This table is for validation, not for detecting exceptions.
SELECT
    defect_type,
    COUNT(*) AS expected_cases,
    SUM(expected_amount) AS sum_of_recorded_expected_amounts
FROM public.ground_truth_exceptions
GROUP BY defect_type
ORDER BY defect_type;


-- 6. Find gateway transactions where the net payout calculation differs.
SELECT
    gateway_txn_id,
    gross_amount,
    fee_deducted,
    gst,
    net_payout,
    ROUND(gross_amount - fee_deducted - gst, 2)
        AS calculated_net_payout,
    ROUND(
        net_payout - (gross_amount - fee_deducted - gst),
        2
    ) AS payout_difference
FROM public.gateway_statement
WHERE ROUND(
    net_payout - (gross_amount - fee_deducted - gst),
    2
) <> 0
ORDER BY gateway_txn_id;

-- The last query should return zero rows when payout arithmetic is consistent.