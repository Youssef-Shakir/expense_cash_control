# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CashMoveSplit(models.TransientModel):
    """Split one POS cash in / out holding several expenses into one line per expense."""
    _name = 'ecc.cash.move.split'
    _description = 'Split a Cash In / Out'

    cash_move_id = fields.Many2one('pos.cash.move', string='Cash In / Out', required=True, readonly=True)
    currency_id = fields.Many2one(related='cash_move_id.currency_id')
    company_id = fields.Many2one(related='cash_move_id.company_id')
    amount = fields.Monetary(related='cash_move_id.amount_abs', string='Amount to Split')
    line_ids = fields.One2many('ecc.cash.move.split.line', 'wizard_id', string='Parts')
    total = fields.Monetary('Total of the Parts', compute='_compute_total', currency_field='currency_id')
    remaining = fields.Monetary('Left to Split', compute='_compute_total', currency_field='currency_id')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        move = self.env['pos.cash.move'].browse(values.get('cash_move_id'))
        if move and 'line_ids' in fields_list:
            values['line_ids'] = [
                (0, 0, {'name': move.name, 'amount': move.amount_abs, 'category_id': move.category_id.id}),
                (0, 0, {'name': '', 'amount': 0.0}),
            ]
        return values

    @api.depends('line_ids.amount', 'amount')
    def _compute_total(self):
        for wizard in self:
            wizard.total = sum(wizard.line_ids.mapped('amount'))
            wizard.remaining = wizard.amount - wizard.total

    def action_confirm(self):
        self.ensure_one()
        parts = [(line.name, line.amount, line.category_id or None)
                 for line in self.line_ids.filtered(lambda l: l.amount or l.name)]
        self.cash_move_id._ecc_split(parts)
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}


class CashMoveSplitLine(models.TransientModel):
    _name = 'ecc.cash.move.split.line'
    _description = 'Part of a split Cash In / Out'

    wizard_id = fields.Many2one('ecc.cash.move.split', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    company_id = fields.Many2one(related='wizard_id.company_id')
    name = fields.Char('Description')
    amount = fields.Monetary('Amount', currency_field='currency_id')
    category_id = fields.Many2one('expense.category', string='Category',
                                  domain="[('company_id', 'in', [False, company_id])]")
