-- Example permissions for a separate non-owner application role.
-- Run while connected to the intended project database as its owner/admin.
-- Replace payment_recon_app with your actual role name if necessary.
-- Do not run this script if you are unsure which role/database is selected.

-- Before loading: allow schema access and the required table operations.
GRANT USAGE, CREATE ON SCHEMA public TO payment_recon_app;
GRANT SELECT, INSERT ON TABLE
    public.internal_orders,
    public.gateway_statement,
    public.bank_statement,
    public.ground_truth_exceptions
TO payment_recon_app;

-- If a different role creates the reconciliation view, run the following
-- after sql/02_reconciliation_exceptions_view.sql has created that view:
-- GRANT SELECT ON public.reconciliation_exceptions TO payment_recon_app;
