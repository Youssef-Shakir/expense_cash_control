# -*- coding: utf-8 -*-
from odoo import _, fields, models, tools
from odoo.exceptions import UserError


class ExpenseLine(models.Model):
    """Every expense of the business in one list, read-only: the recorded expenses and the POS cash-outs
    classified to an expense category. A classified cash-out is already booked on the category's account
    by its own journal entry, so it is only shown here, never recorded a second time."""
    _name = 'ecc.expense.line'
    _description = 'Expenses and POS Cash-Outs'
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'name'

    date = fields.Date(readonly=True)
    name = fields.Char('Description', readonly=True)
    source = fields.Selection([('expense', 'Expense'), ('pos', 'POS Cash-Out')], readonly=True)
    category_id = fields.Many2one('expense.category', string='Category', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Vendor', readonly=True)
    amount = fields.Monetary(readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    user_id = fields.Many2one('res.users', string='Recorded By', readonly=True)
    payment_mode = fields.Selection([('paid', 'Paid Now'), ('to_pay', 'To Pay Later')], string='Payment',
                                    readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('posted', 'Posted')], string='Status', readonly=True)
    session_id = fields.Many2one('pos.session', string='POS Session', readonly=True)
    config_id = fields.Many2one('pos.config', string='Point of Sale', readonly=True)
    expense_id = fields.Many2one('expense.express', string='Expense', readonly=True)
    cash_move_id = fields.Many2one('pos.cash.move', string='POS Cash-Out', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT e.id * 2 AS id, e.date, e.name, 'expense' AS source, e.category_id, e.partner_id,
                       e.amount, e.currency_id, e.company_id, e.user_id, e.payment_mode, e.state,
                       NULL::integer AS session_id, NULL::integer AS config_id,
                       e.id AS expense_id, NULL::integer AS cash_move_id
                  FROM expense_express e
                UNION ALL
                SELECT m.id * 2 + 1 AS id, m.date, m.name, 'pos' AS source, m.category_id, NULL::integer,
                       m.amount_abs, c.currency_id, m.company_id, m.user_id, 'paid', 'posted',
                       m.session_id, m.config_id, NULL::integer, m.id
                  FROM pos_cash_move m
                  JOIN res_company c ON c.id = m.company_id
                 WHERE m.move_type = 'out' AND m.state = 'classified' AND m.classification_type = 'category'
            )""" % self._table)

    def action_open_source(self):
        self.ensure_one()
        record = self.expense_id or self.cash_move_id
        if not record:
            raise UserError(_('Nothing to open.'))
        return {'type': 'ir.actions.act_window', 'res_model': record._name, 'res_id': record.id,
                'views': [(False, 'form')], 'target': 'current'}
