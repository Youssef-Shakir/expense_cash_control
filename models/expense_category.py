# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ExpenseCategory(models.Model):
    """Expense categories with linked accounts.

    The same categories are used for expenses, POS cash in/out and cash
    difference classification, so there is one list to maintain.
    """
    _name = 'expense.category'
    _description = 'Expense Category'
    _inherit = ['pos.load.mixin']
    _order = 'sequence, name'

    name = fields.Char('Category Name', required=True, translate=True)
    code = fields.Char('Code', required=True)
    sequence = fields.Integer('Sequence', default=10)
    active = fields.Boolean('Active', default=True)
    color = fields.Integer('Color')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        help='Leave empty to share this category between companies.',
    )

    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=True,
        help='Account used for this category in journal entries '
             '(usually an expense account, or an income/equity account for cash in).',
    )

    available_in_pos = fields.Boolean(
        'Available in POS',
        help='Show this category in the POS Cash In / Cash Out popup.',
    )
    pos_cash_type = fields.Selection([
        ('out', 'Cash Out'),
        ('in', 'Cash In'),
        ('both', 'Cash In & Out'),
    ], string='POS Cash Direction', default='out', required=True,
        help='Which POS cash moves can use this category.')

    expense_count = fields.Integer('Expenses', compute='_compute_expense_stats')
    expense_total = fields.Monetary('Total Expenses', compute='_compute_expense_stats')
    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
    )

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Category code must be unique!')
    ]

    def _compute_currency_id(self):
        for category in self:
            category.currency_id = (category.company_id or self.env.company).currency_id

    def _compute_expense_stats(self):
        data = self.env['expense.express']._read_group(
            [('category_id', 'in', self.ids)],
            ['category_id'],
            ['__count', 'amount:sum'],
        )
        stats = {category.id: (count, total) for category, count, total in data}
        for category in self:
            category.expense_count, category.expense_total = stats.get(category.id, (0, 0.0))

    def action_view_expenses(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('expense_cash_control.action_expense_express')
        action['domain'] = [('category_id', '=', self.id)]
        action['context'] = {'default_category_id': self.id}
        return action

    # -------------------------------------------------------------------------
    # POS data loading
    # -------------------------------------------------------------------------

    @api.model
    def _load_pos_data_domain(self, data):
        config = data['pos.config']['data'][0]
        if not config.get('use_cash_categories'):
            return False
        domain = [
            ('available_in_pos', '=', True),
            ('company_id', 'in', [False, config['company_id']]),
        ]
        if config.get('cash_category_ids'):
            domain.append(('id', 'in', config['cash_category_ids']))
        return domain

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ['id', 'name', 'pos_cash_type', 'color', 'sequence']
