-- 03_ground_truth_validation.sql
-- Compare the detected exceptions with the synthetic test results.
-- The ground-truth table is used only for evaluation.

-- 1. Check row counts.
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

UNION ALL

SELECT 'reconciliation_exceptions', COUNT(*)
FROM public.reconciliation_exceptions

ORDER BY table_name;


-- 2. Count the expected test cases in each category.
SELECT
    defect_type,
    COUNT(*) AS expected_cases,
    SUM(expected_amount) AS sum_of_recorded_expected_amounts
FROM public.ground_truth_exceptions
GROUP BY defect_type
ORDER BY defect_type;


-- 3. Summarize the exceptions found by the detector.
-- Amounts across categories should not be treated as net financial loss.
SELECT
    defect_type,
    COUNT(*) AS detected_cases,
    SUM(amount_under_review) AS amount_under_review
FROM public.reconciliation_exceptions
GROUP BY defect_type
ORDER BY defect_type;


-- 4. Compare detected exception IDs and amounts with ground truth.
WITH expected AS (
    SELECT
        defect_type,
        entity_id,
        expected_amount
    FROM public.ground_truth_exceptions
),
detected AS (
    SELECT
        defect_type,
        entity_id,
        amount_under_review
    FROM public.reconciliation_exceptions
),
comparison AS (
    SELECT
        COALESCE(e.defect_type, d.defect_type) AS defect_type,
        e.entity_id AS expected_entity_id,
        d.entity_id AS detected_entity_id,
        e.expected_amount,
        d.amount_under_review,
        CASE
            WHEN e.entity_id IS NOT NULL
             AND d.entity_id IS NOT NULL
            THEN ROUND(d.amount_under_review - e.expected_amount, 2)
            ELSE NULL
        END AS amount_difference,
        CASE
            WHEN e.entity_id IS NOT NULL
             AND d.entity_id IS NOT NULL
                THEN 'MATCHED'
            WHEN e.entity_id IS NOT NULL
             AND d.entity_id IS NULL
                THEN 'FALSE_NEGATIVE'
            ELSE 'FALSE_POSITIVE'
        END AS match_status
    FROM expected AS e
    FULL OUTER JOIN detected AS d
        ON e.defect_type = d.defect_type
       AND e.entity_id = d.entity_id
)
SELECT
    defect_type,
    COUNT(*) FILTER (
        WHERE match_status = 'MATCHED'
    ) AS matched_cases,
    COUNT(*) FILTER (
        WHERE match_status = 'FALSE_POSITIVE'
    ) AS false_positives,
    COUNT(*) FILTER (
        WHERE match_status = 'FALSE_NEGATIVE'
    ) AS false_negatives,
    COUNT(*) FILTER (
        WHERE match_status = 'MATCHED'
          AND amount_difference = 0
    ) AS amount_matches,
    COUNT(*) FILTER (
        WHERE match_status = 'MATCHED'
          AND amount_difference <> 0
    ) AS amount_mismatches,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE match_status = 'MATCHED'
        ) /
        NULLIF(
            COUNT(*) FILTER (
                WHERE match_status IN (
                    'MATCHED',
                    'FALSE_POSITIVE'
                )
            ),
            0
        ),
        2
    ) AS precision_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE match_status = 'MATCHED'
        ) /
        NULLIF(
            COUNT(*) FILTER (
                WHERE match_status IN (
                    'MATCHED',
                    'FALSE_NEGATIVE'
                )
            ),
            0
        ),
        2
    ) AS recall_pct
FROM comparison
GROUP BY defect_type
ORDER BY defect_type;


-- 5. Show only records with amount mismatches.
-- This query should return zero rows when all amounts match.
WITH expected AS (
    SELECT
        defect_type,
        entity_id,
        expected_amount
    FROM public.ground_truth_exceptions
),
detected AS (
    SELECT
        defect_type,
        entity_id,
        amount_under_review
    FROM public.reconciliation_exceptions
)
SELECT
    e.defect_type,
    e.entity_id,
    e.expected_amount,
    d.amount_under_review,
    ROUND(
        d.amount_under_review - e.expected_amount,
        2
    ) AS amount_difference
FROM expected AS e
JOIN detected AS d
    ON e.defect_type = d.defect_type
   AND e.entity_id = d.entity_id
WHERE ROUND(
    d.amount_under_review - e.expected_amount,
    2
) <> 0
ORDER BY e.defect_type, e.entity_id;