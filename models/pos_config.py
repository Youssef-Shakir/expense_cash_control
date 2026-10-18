# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    use_cash_categories = fields.Boolean(
        string='Cash In/Out Categories',
        help='Let the cashier pick a category in the Cash In / Cash Out popup. '
             'The move is posted directly on the category account.')
    cash_category_required = fields.Boolean(
        string='Category Required',
        help='The cashier must pick a category. Otherwise uncategorized moves '
             'go to the back office review.')
    cash_category_ids = fields.Many2many(
        'expense.category',
        string='Available Categories',
        domain=[('available_in_pos', '=', True)],
        help='Limit categories available in this POS. Leave empty for all POS categories.')
