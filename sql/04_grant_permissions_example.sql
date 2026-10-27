-- Example permissions for a separate non-owner application role.
-- Run while connected to the intended project database as its owner/admin.
-- Create the login role separately if it does not already exist.
-- Replace payment_recon_app with your configured role name if necessary.
-- Do not run this script if you are unsure which database is selected.

-- Run after sql/01_create_tables.sql and before loading the CSV files.
-- The application role needs schema usage and table-level SELECT/INSERT only.
-- It does not need CREATE privilege on the public schema.
GRANT USAGE ON SCHEMA public TO payment_recon_app;

GRANT SELECT, INSERT ON TABLE
    public.internal_orders,
    public.gateway_statement,
    public.bank_statement,
    public.ground_truth_exceptions
TO payment_recon_app;

-- After sql/02_reconciliation_exceptions_view.sql creates the view, run this
-- separately as the view owner or a database administrator if the application
-- role is not the view owner:
-- GRANT SELECT ON public.reconciliation_exceptions TO payment_recon_app;
