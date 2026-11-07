# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SessionLateExpense(models.TransientModel):
    """Record a cash-out the cashier paid from the drawer but forgot to enter in the POS."""
    _name = 'ecc.session.late.expense'
    _description = 'Forgotten Expense (after closing)'

    session_id = fields.Many2one('pos.session', string='Session', required=True, readonly=True)
    company_id = fields.Many2one(related='session_id.company_id')
    currency_id = fields.Many2one(related='session_id.currency_id')
    name = fields.Char('Reason', required=True, help='What was paid, e.g. "Vegetables - Abu Ali".')
    amount = fields.Monetary('Amount', required=True, currency_field='currency_id')
    category_id = fields.Many2one(
        'expense.category', string='Category',
        domain="[('pos_cash_type', 'in', ('out', 'both')), ('company_id', 'in', [False, company_id])]",
        help='Leave empty to classify it later in the Cash In / Out tab (category or partner payment).')

    counted = fields.Monetary(related='session_id.cash_register_balance_end_real', string='Counted')
    expected_before = fields.Monetary('Expected Now', compute='_compute_preview', currency_field='currency_id')
    expected_after = fields.Monetary('Expected After', compute='_compute_preview', currency_field='currency_id')
    difference_before = fields.Monetary('Difference Now', compute='_compute_preview', currency_field='currency_id')
    difference_after = fields.Monetary('Difference After', compute='_compute_preview', currency_field='currency_id')

    @api.depends('amount', 'session_id')
    def _compute_preview(self):
        for wizard in self:
            session = wizard.session_id
            wizard.expected_before = session.cash_register_balance_end
            wizard.expected_after = session.cash_register_balance_end - (wizard.amount or 0.0)
            wizard.difference_before = session.cash_register_difference
            wizard.difference_after = session.cash_register_difference + (wizard.amount or 0.0)

    def action_confirm(self):
        self.ensure_one()
        self.session_id._ecc_add_late_expense(self.name, self.amount, self.category_id or None)
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}
