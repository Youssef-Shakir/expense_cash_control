# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SessionCardDifference(models.TransientModel):
    """Card difference not counted at closing (e.g. an order paid by card but rung up as cash)."""
    _name = 'ecc.session.card.difference'
    _description = 'Forgotten Card Difference'

    session_id = fields.Many2one('pos.session', string='Session', required=True, readonly=True)
    company_id = fields.Many2one(related='session_id.company_id')
    currency_id = fields.Many2one(related='session_id.currency_id')
    method_ids = fields.Many2many('pos.payment.method', compute='_compute_method_ids')
    payment_method_id = fields.Many2one(
        'pos.payment.method', string='Card / Bank Method', required=True, domain="[('id', 'in', method_ids)]")
    difference_type = fields.Selection([
        ('gain', 'The terminal got more (paid by card, recorded as cash)'),
        ('loss', 'The terminal got less (paid in cash, recorded as card)'),
    ], string='What happened', required=True, default='gain')
    amount = fields.Monetary('Amount', required=True, currency_field='currency_id')
    name = fields.Char('Reason', help='e.g. "Order 0042 paid by card, entered as cash".')
    cash_difference = fields.Monetary(related='session_id.cash_register_difference', string='Cash Difference')
    card_before = fields.Monetary('Card Difference Now', compute='_compute_preview', currency_field='currency_id')
    card_after = fields.Monetary('Card Difference After', compute='_compute_preview', currency_field='currency_id')
    total_after = fields.Monetary('Total Difference After', compute='_compute_preview',
                                  currency_field='currency_id')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        session = self.env['pos.session'].browse(values.get('session_id'))
        if session and 'payment_method_id' in fields_list and not values.get('payment_method_id'):
            values['payment_method_id'] = self.env['cash.difference.reconciliation']._card_methods(session)[:1].id
        return values

    @api.depends('session_id')
    def _compute_method_ids(self):
        for wizard in self:
            wizard.method_ids = self.env['cash.difference.reconciliation']._card_methods(wizard.session_id)

    @api.depends('session_id', 'amount', 'difference_type')
    def _compute_preview(self):
        for wizard in self:
            session = wizard.session_id
            change = (wizard.amount or 0.0) * (1 if wizard.difference_type == 'gain' else -1)
            wizard.card_before = session.card_difference
            wizard.card_after = session.card_difference + change
            wizard.total_after = session.total_difference + change

    def action_confirm(self):
        self.ensure_one()
        self.session_id._ecc_add_card_difference(self.payment_method_id, self.amount, self.difference_type,
                                                 self.name)
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}
