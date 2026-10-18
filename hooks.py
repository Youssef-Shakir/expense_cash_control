# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

# Modules merged into this one. They define the same models, so they can't be
# installed side by side: their data has to be moved with the rename script.
REPLACED_MODULES = ('expense_express', 'pos_cash_category')


def pre_init_hook(env):
    env.cr.execute(
        "SELECT name FROM ir_module_module WHERE name IN %s AND state IN ('installed', 'to upgrade')",
        [REPLACED_MODULES],
    )
    installed = [row[0] for row in env.cr.fetchall()]
    if installed:
        raise UserError(
            "Expenses & Cash Control replaces %s. Do not install it next to them: run "
            "expense_cash_control/scripts/migrate_from_expense_express.sql first, then upgrade "
            "expense_cash_control (see README)." % ', '.join(installed)
        )
