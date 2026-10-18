-- Move an existing "Expenses Press" (expense_express) database to
-- "Expenses & Cash Control" (expense_cash_control) without losing data.
--
-- The new module keeps the same models (expense.express, expense.category,
-- cash.difference.reconciliation), so the module is renamed in place: every
-- record, XML id and journal entry link stays as it is.
--
-- 1. BACK UP THE DATABASE.
-- 2. Stop Odoo (or make sure nobody is using it).
-- 3. Put expense_cash_control in the addons path and REMOVE expense_express
--    from it (otherwise "Update Apps List" shows it again).
-- 4. psql -d <db> -f migrate_from_expense_express.sql
-- 5. odoo -d <db> -u expense_cash_control --stop-after-init
--
-- Safe to run twice: it does nothing when expense_express is not there.

BEGIN;

DO $$
DECLARE
    old_name CONSTANT varchar := 'expense_express';
    new_name CONSTANT varchar := 'expense_cash_control';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM ir_module_module WHERE name = old_name) THEN
        RAISE NOTICE '% is not in this database, nothing to do.', old_name;
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM ir_module_module WHERE name = new_name AND state = 'installed') THEN
        RAISE EXCEPTION '% is already installed: refusing to merge two installed modules.', new_name;
    END IF;

    -- An "uninstalled" entry created by "Update Apps List" would clash with the rename.
    DELETE FROM ir_module_module_dependency
     WHERE module_id IN (SELECT id FROM ir_module_module WHERE name = new_name);
    DELETE FROM ir_model_data
     WHERE model = 'ir.module.module'
       AND res_id IN (SELECT id FROM ir_module_module WHERE name = new_name);
    DELETE FROM ir_module_module WHERE name = new_name;

    UPDATE ir_module_module SET name = new_name WHERE name = old_name;
    UPDATE ir_module_module_dependency SET name = new_name WHERE name = old_name;
    UPDATE ir_model_data SET module = new_name WHERE module = old_name;
    UPDATE ir_model_data SET name = 'module_' || new_name
     WHERE module = 'base' AND model = 'ir.module.module' AND name = 'module_' || old_name;

    -- Make Odoo run the upgrade (installed version 18.0.1.x < 18.0.2.0.0).
    UPDATE ir_module_module SET state = 'to upgrade' WHERE name = new_name AND state = 'installed';

    RAISE NOTICE 'Renamed % to %. Now run: odoo -u %', old_name, new_name, new_name;
END $$;

COMMIT;
