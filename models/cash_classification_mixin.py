# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CashClassificationMixin(models.AbstractModel):
    """Where a POS cash amount ends up: an expense category, or a partner.

    "Partner Payment" posts the amount on the partner's payable (money out) or
    receivable (money in) account with the partner set, so it shows on the
    partner's bills/invoices as an outstanding payment, or is reconciled with
    the chosen bill right away.
    """
    _name = 'ecc.cash.classification.mixin'
    _description = 'Cash Classification (category or partner)'

    classification_type = fields.Selection([
        ('category', 'Expense Category'),
        ('partner', 'Partner Payment'),
    ], string='Goes To', default='category', required=True, tracking=True,
        help='Expense Category: the amount is an expense / income of the business.\n'
             'Partner Payment: the money was paid to (or received from) a partner, e.g. a vendor paid '
             'from the cash drawer. It is recorded on the partner account to reconcile with the bills.')
    partner_id = fields.Many2one('res.partner', string='Partner', tracking=True)
    partner_account_id = fields.Many2one(
        'account.account', string='Partner Account',
        compute='_compute_partner_account_id', store=True, readonly=False, precompute=True,
        help='Payable account for money paid out, receivable account for money received.')
    cash_direction = fields.Selection(
        [('out', 'Money Out'), ('in', 'Money In')], compute='_compute_cash_direction')
    bill_id = fields.Many2one(
        'account.move', string='Bill / Invoice', tracking=True,
        domain="[('state', '=', 'posted'), ('payment_state', 'in', ('not_paid', 'partial')), "
               "('move_type', 'in', ('in_invoice', 'out_refund') if cash_direction == 'out' else ('out_invoice', 'in_refund')), "
               "('commercial_partner_id', '=', partner_commercial_id)]",
        help='Optional: reconcile right away with this open bill. Leave empty to reconcile later '
             'from the bill (it shows as an outstanding payment).')
    partner_commercial_id = fields.Many2one(related='partner_id.commercial_partner_id', string='Commercial Partner')

    def _get_cash_direction(self):
        """'out' when money left the cash drawer, 'in' when money came in."""
        raise NotImplementedError()

    def _compute_cash_direction(self):
        for record in self:
            record.cash_direction = record._get_cash_direction()

    @api.depends('partner_id', 'classification_type')
    def _compute_partner_account_id(self):
        for record in self:
            partner = record.partner_id.commercial_partner_id
            if record.classification_type != 'partner' or not partner:
                record.partner_account_id = False
                continue
            partner = partner.with_company(record.company_id or self.env.company)
            if record._get_cash_direction() == 'out':
                record.partner_account_id = partner.property_account_payable_id
            else:
                record.partner_account_id = partner.property_account_receivable_id

    @api.onchange('partner_id')
    def _onchange_partner_id_reset_bill(self):
        if self.bill_id and self.bill_id.commercial_partner_id != self.partner_id.commercial_partner_id:
            self.bill_id = False

    def _get_classification_account(self):
        """Account the amount must be moved to, with checks."""
        self.ensure_one()
        if self.classification_type == 'partner':
            if not self.partner_id:
                raise UserError(_('Please choose the partner for "%s".', self.display_name))
            if not self.partner_account_id:
                raise UserError(_('The partner "%s" has no payable/receivable account.', self.partner_id.display_name))
            return self.partner_account_id
        if not self.category_id:
            raise UserError(_('Please choose a category for "%s" first.', self.display_name))
        if not self.category_id.account_id:
            raise UserError(_('The category "%s" has no account.', self.category_id.name))
        return self.category_id.account_id

    def _get_classification_partner(self):
        self.ensure_one()
        return self.partner_id.commercial_partner_id if self.classification_type == 'partner' else self.env['res.partner']

    def _get_classification_label(self):
        self.ensure_one()
        if self.classification_type == 'partner':
            return self.partner_id.display_name
        return self.category_id.name

    def _reconcile_with_bill(self, lines):
        """Reconcile ``lines`` (on the partner account) with the chosen bill."""
        self.ensure_one()
        if self.classification_type != 'partner' or not self.bill_id:
            return
        account = self.partner_account_id
        bill_lines = self.bill_id.line_ids.filtered(lambda l: l.account_id == account and not l.reconciled)
        own_lines = lines.filtered(lambda l: l.account_id == account and not l.reconciled)
        if not bill_lines:
            raise UserError(_('The bill %(bill)s has nothing left to pay on account %(account)s.',
                              bill=self.bill_id.display_name, account=account.display_name))
        (bill_lines + own_lines).reconcile()

    @api.model
    def _unreconcile_lines(self, lines):
        lines.filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids).remove_move_reconcile()
