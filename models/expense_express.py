# -*- coding: utf-8 -*-
from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError


class ExpenseExpress(models.Model):
    """Simple expense recording with automatic accounting.

    - "Paid now": a journal entry crediting the cash/bank account.
    - "To pay later": a vendor bill that waits for payment like any bill.
    """
    _name = 'expense.express'
    _description = 'Expense'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    # Changing one of these regenerates the accounting document.
    _ACCOUNTING_FIELDS = {
        'name', 'amount', 'category_id', 'date', 'journal_id',
        'payment_mode', 'partner_id', 'due_date', 'currency_id',
    }

    name = fields.Char(
        'Description',
        required=True,
        tracking=True,
        help='What was this expense for?'
    )
    amount = fields.Monetary(
        'Amount',
        required=True,
        tracking=True,
        currency_field='currency_id'
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True
    )
    date = fields.Date(
        'Date',
        required=True,
        tracking=True,
        default=fields.Date.context_today
    )
    category_id = fields.Many2one(
        'expense.category',
        string='Category',
        required=True,
        tracking=True,
        domain="[('company_id', 'in', [False, company_id])]",
    )
    category_color = fields.Integer(related='category_id.color')
    notes = fields.Text('Notes')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    user_id = fields.Many2one(
        'res.users',
        string='Recorded By',
        default=lambda self: self.env.user,
        readonly=True,
    )

    payment_mode = fields.Selection([
        ('paid', 'Paid Now'),
        ('to_pay', 'To Pay Later'),
    ], string='Payment', default='paid', required=True, tracking=True,
        help='Paid Now: the money already left the cash box or bank account.\n'
             'To Pay Later: records a vendor bill that waits for payment.')
    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        tracking=True,
        help='Required for expenses to pay later (vendor bill).',
    )
    due_date = fields.Date('Due Date', help='When the bill should be paid.')

    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        required=True,
        compute='_compute_journal_id', store=True, readonly=False, precompute=True,
        domain="[('company_id', '=', company_id), "
               "('type', 'in', ['purchase'] if payment_mode == 'to_pay' else ['cash', 'bank'])]",
    )
    move_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        copy=False
    )
    move_type = fields.Selection(related='move_id.move_type')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
    ], string='Status', default='draft', readonly=True, copy=False, tracking=True)

    payment_state = fields.Selection([
        ('not_paid', 'Not Paid'),
        ('in_payment', 'In Payment'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
    ], string='Payment Status', compute='_compute_payment_state', store=True)
    amount_residual = fields.Monetary(
        'Amount Due',
        compute='_compute_payment_state', store=True,
        currency_field='currency_id',
    )
    is_overdue = fields.Boolean(compute='_compute_is_overdue', search='_search_is_overdue')
    is_locked = fields.Boolean(
        compute='_compute_is_locked',
        help='The bill already has a payment: the expense can no longer be changed.')

    attachment_ids = fields.Many2many(
        'ir.attachment',
        'expense_express_ir_attachment_rel',
        'expense_id', 'attachment_id',
        string='Receipts',
        copy=False,
        help='Photos of receipts, invoices or any supporting document.',
    )
    attachment_count = fields.Integer('Receipt Count', compute='_compute_attachment_count')

    # -------------------------------------------------------------------------
    # COMPUTE
    # -------------------------------------------------------------------------

    @api.depends('payment_mode', 'company_id')
    def _compute_journal_id(self):
        for expense in self:
            wanted = ['purchase'] if expense.payment_mode == 'to_pay' else ['cash', 'bank']
            if expense.journal_id.type in wanted and expense.journal_id.company_id == expense.company_id:
                continue
            expense.journal_id = expense._default_journal(expense.payment_mode, expense.company_id)

    @api.model
    def _default_journal(self, payment_mode='paid', company=None):
        company = company or self.env.company
        journal_types = ['purchase'] if payment_mode == 'to_pay' else ['cash', 'bank']
        Journal = self.env['account.journal']
        for journal_type in journal_types:
            journal = Journal.search([
                ('type', '=', journal_type),
                ('company_id', '=', company.id),
            ], limit=1)
            if journal:
                return journal
        return Journal

    @api.depends('payment_mode', 'state', 'amount', 'move_id.payment_state', 'move_id.amount_residual')
    def _compute_payment_state(self):
        for expense in self:
            if expense.payment_mode == 'to_pay' and expense.move_id.move_type == 'in_invoice':
                state = expense.move_id.payment_state
                expense.payment_state = state if state in ('in_payment', 'partial', 'paid') else 'not_paid'
                expense.amount_residual = expense.move_id.amount_residual
            elif expense.payment_mode == 'to_pay':
                expense.payment_state = 'not_paid'
                expense.amount_residual = expense.amount
            else:
                expense.payment_state = 'paid'
                expense.amount_residual = 0.0

    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for expense in self:
            expense.is_overdue = bool(
                expense.payment_mode == 'to_pay'
                and expense.payment_state in ('not_paid', 'partial')
                and (expense.due_date or expense.date) < today
            )

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Operation not supported'))
        today = fields.Date.context_today(self)
        domain = [
            ('payment_mode', '=', 'to_pay'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            '|',
            '&', ('due_date', '!=', False), ('due_date', '<', today),
            '&', ('due_date', '=', False), ('date', '<', today),
        ]
        overdue_ids = self._search(domain)
        if (operator == '=') == value:
            return [('id', 'in', overdue_ids)]
        return [('id', 'not in', overdue_ids)]

    @api.depends('move_id.payment_state', 'move_id.move_type')
    def _compute_is_locked(self):
        for expense in self:
            expense.is_locked = (
                expense.move_id.move_type == 'in_invoice'
                and expense.move_id.payment_state not in ('not_paid', 'reversed')
            )

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for expense in self:
            expense.attachment_count = len(expense.attachment_ids)

    # -------------------------------------------------------------------------
    # CONSTRAINTS / ONCHANGE
    # -------------------------------------------------------------------------

    @api.constrains('amount')
    def _check_amount(self):
        for expense in self:
            if expense.currency_id.compare_amounts(expense.amount, 0.0) <= 0:
                raise UserError(_('The amount of an expense must be greater than zero.'))

    @api.constrains('payment_mode', 'partner_id')
    def _check_partner(self):
        for expense in self:
            if expense.payment_mode == 'to_pay' and not expense.partner_id:
                raise UserError(_('Please select the vendor for "%s": an expense to pay later is recorded as a vendor bill.', expense.name))

    # -------------------------------------------------------------------------
    # ACCOUNTING
    # -------------------------------------------------------------------------

    def _get_expense_account(self):
        self.ensure_one()
        account = self.category_id.account_id
        if not account:
            raise UserError(_('Please set an expense account on category "%s"', self.category_id.name))
        return account

    def _get_credit_account(self):
        """Account the money leaves from, for expenses paid now."""
        self.ensure_one()
        journal = self.journal_id
        if journal.type in ('cash', 'bank'):
            credit_account = journal.default_account_id
        else:
            # Expenses recorded before "To Pay Later" existed may use a purchase journal.
            credit_account = self.company_id.account_journal_payment_credit_account_id or journal.default_account_id
        if not credit_account:
            raise UserError(_('Please configure a default account on journal "%s"', journal.name))
        return credit_account

    def _prepare_entry_lines(self):
        self.ensure_one()
        partner_id = self.partner_id.id
        return [
            Command.create({
                'name': self.name,
                'account_id': self._get_expense_account().id,
                'partner_id': partner_id,
                'debit': self.amount,
                'credit': 0.0,
            }),
            Command.create({
                'name': self.name,
                'account_id': self._get_credit_account().id,
                'partner_id': partner_id,
                'debit': 0.0,
                'credit': self.amount,
            }),
        ]

    def _prepare_bill_lines(self):
        self.ensure_one()
        return [Command.create({
            'name': self.name,
            'account_id': self._get_expense_account().id,
            'quantity': 1.0,
            'price_unit': self.amount,
            # The amount typed is what is owed: no taxes added on top.
            'tax_ids': [Command.clear()],
        })]

    def _prepare_move_values(self):
        """Values to create (or rewrite) the accounting document."""
        self.ensure_one()
        if self.payment_mode == 'to_pay':
            if self.journal_id.type != 'purchase':
                raise UserError(_('An expense to pay later needs a purchase journal (e.g. Vendor Bills).'))
            return {
                'move_type': 'in_invoice',
                'partner_id': self.partner_id.id,
                'invoice_date': self.date,
                'date': self.date,
                'invoice_date_due': self.due_date or False,
                'ref': self.name,
                'journal_id': self.journal_id.id,
                'company_id': self.company_id.id,
                'currency_id': self.currency_id.id,
                'narration': self.notes or False,
                'invoice_line_ids': self._prepare_bill_lines(),
            }
        return {
            'move_type': 'entry',
            'date': self.date,
            'ref': self.name,
            'journal_id': self.journal_id.id,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'narration': self.notes or False,
            'line_ids': self._prepare_entry_lines(),
        }

    def _check_editable_move(self):
        for expense in self:
            if expense.is_locked:
                raise UserError(_(
                    'The bill of "%s" already has a payment. Unreconcile the payment on the bill first, '
                    'then edit the expense.', expense.name))

    def _sync_move(self):
        """Create the accounting document, or rewrite the existing one in place.

        Rewriting keeps the entry number, so editing an old expense never
        leaves a gap in the journal sequence.
        """
        for expense in self:
            vals = expense._prepare_move_values()
            move = expense.move_id
            if move and move.move_type == vals['move_type'] and move.journal_id.id == vals['journal_id']:
                if move.state == 'posted':
                    move.button_draft()
                lines_key = 'invoice_line_ids' if vals['move_type'] == 'in_invoice' else 'line_ids'
                vals[lines_key] = [Command.clear()] + vals[lines_key]
                vals.pop('move_type')
                move.write(vals)
            else:
                old_move = move
                move = self.env['account.move'].create(vals)
                expense.move_id = move
                old_move._expense_remove()
            move.action_post()
            expense._attach_receipts_to_move()
            if expense.state != 'posted':
                expense.state = 'posted'

    def _attach_receipts_to_move(self):
        """Copy the receipts on the journal entry / bill so the accountant sees them."""
        for expense in self.filtered('move_id'):
            move = expense.move_id
            existing = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.move'), ('res_id', '=', move.id),
            ]).mapped('checksum')
            for attachment in expense.attachment_ids:
                if attachment.checksum not in existing:
                    attachment.copy({'res_model': 'account.move', 'res_id': move.id})
            if expense.attachment_ids and not move.message_main_attachment_id:
                move.message_main_attachment_id = move.attachment_ids[:1]

    def action_post(self):
        """Create and post the accounting document."""
        self.filtered(lambda e: e.state != 'posted')._sync_move()

    def action_register_payment(self):
        self.ensure_one()
        if self.payment_mode != 'to_pay' or self.move_id.move_type != 'in_invoice':
            raise UserError(_('Only expenses to pay later have a bill to pay.'))
        return self.move_id.action_register_payment()

    def action_mark_paid_now(self):
        """Shortcut: convert an unpaid expense into one already paid in cash/bank."""
        self.ensure_one()
        self.write({'payment_mode': 'paid'})

    # -------------------------------------------------------------------------
    # ORM
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Create expense and post it right away."""
        records = super().create(vals_list)
        records._link_attachments()
        records.action_post()
        return records

    def write(self, vals):
        if self._ACCOUNTING_FIELDS & set(vals):
            self._check_editable_move()
        result = super().write(vals)
        if 'attachment_ids' in vals:
            self._link_attachments()
        if self._ACCOUNTING_FIELDS & set(vals):
            self._sync_move()
        elif 'attachment_ids' in vals:
            self._attach_receipts_to_move()
        return result

    def _link_attachments(self):
        """Files uploaded on a new record are not linked to it yet."""
        for expense in self:
            unlinked = expense.attachment_ids.filtered(
                lambda a: a.res_model != self._name or a.res_id != expense.id)
            unlinked.sudo().write({'res_model': self._name, 'res_id': expense.id})

    def unlink(self):
        """Remove the accounting document with the expense."""
        self._check_editable_move()
        moves = self.mapped('move_id')
        result = super().unlink()
        moves._expense_remove()
        return result

    def action_view_move(self):
        """Open related journal entry / bill."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Bill') if self.move_id.move_type == 'in_invoice' else _('Journal Entry'),
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _expense_remove(self):
        """Delete moves of removed expenses, or cancel them when deleting
        would leave a gap in the sequence."""
        for move in self:
            if move.state == 'posted':
                move.button_draft()
            try:
                with self.env.cr.savepoint():
                    move.unlink()
            except UserError:
                move.button_cancel()
