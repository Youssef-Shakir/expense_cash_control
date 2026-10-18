# -*- coding: utf-8 -*-
from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError


class PosCashMove(models.Model):
    """A Cash In / Cash Out made by a cashier from the POS.

    Categorized at the till: the statement line already posts on the
    category account. Not categorized: it sits on the cash journal's suspense
    account until a manager classifies it here.
    """
    _name = 'pos.cash.move'
    _description = 'POS Cash In/Out'
    _inherit = ['mail.thread', 'ecc.cash.classification.mixin']
    _order = 'date desc, id desc'
    _rec_name = 'name'

    name = fields.Char('Reason', required=True, readonly=True)
    statement_line_id = fields.Many2one(
        'account.bank.statement.line', string='Statement Line',
        required=True, readonly=True, ondelete='cascade', index=True)
    account_move_id = fields.Many2one(related='statement_line_id.move_id', string='Journal Entry')
    session_id = fields.Many2one('pos.session', string='POS Session', readonly=True, index=True)
    config_id = fields.Many2one(related='session_id.config_id', string='Point of Sale', store=True)
    journal_id = fields.Many2one(related='statement_line_id.journal_id', string='Cash Journal', store=True)
    company_id = fields.Many2one(related='statement_line_id.company_id', store=True)
    currency_id = fields.Many2one(related='statement_line_id.currency_id', string='Currency')
    date = fields.Date(related='statement_line_id.date', store=True)
    amount = fields.Monetary(
        'Signed Amount', related='statement_line_id.amount', store=True,
        help='Positive for cash in, negative for cash out')
    amount_abs = fields.Monetary('Amount', compute='_compute_amount_abs', store=True)
    move_type = fields.Selection([
        ('in', 'Cash In'),
        ('out', 'Cash Out'),
    ], string='Type', compute='_compute_move_type', store=True)
    user_id = fields.Many2one('res.users', string='Cashier', readonly=True)

    category_id = fields.Many2one(
        'expense.category', string='Category', tracking=True,
        domain="[('company_id', 'in', [False, company_id])]",
        help='In the POS only the categories of the right direction are offered; '
             'here any category can be used.')
    state = fields.Selection([
        ('to_classify', 'To Classify'),
        ('classified', 'Classified'),
    ], string='Status', default='to_classify', required=True, readonly=True, tracking=True)
    classified_at_pos = fields.Boolean('Categorized at POS', readonly=True)
    classified_by_id = fields.Many2one('res.users', string='Classified By', readonly=True)
    classified_date = fields.Datetime('Classified On', readonly=True)
    notes = fields.Text('Notes')

    _sql_constraints = [
        ('statement_line_unique', 'UNIQUE(statement_line_id)', 'This cash move is already tracked.'),
    ]

    def _get_cash_direction(self):
        self.ensure_one()
        return 'in' if self.amount >= 0 else 'out'

    @api.depends('amount')
    def _compute_amount_abs(self):
        for move in self:
            move.amount_abs = abs(move.amount)

    @api.depends('amount')
    def _compute_move_type(self):
        for move in self:
            move.move_type = 'in' if move.amount >= 0 else 'out'

    # -------------------------------------------------------------------------
    # DETECTION
    # -------------------------------------------------------------------------

    @api.model
    def _sync_from_statement_lines(self, sessions=None):
        """Track POS cash in/out lines still waiting on the suspense account.

        Cash payments of orders and cash differences have a real counterpart
        account, so only uncategorized cash in/out are picked up.
        """
        domain = [('pos_session_id', '!=', False)]
        if sessions is not None:
            domain = [('pos_session_id', 'in', sessions.ids)]
        tracked = self.search([]).statement_line_id
        st_lines = self.env['account.bank.statement.line'].search(domain + [('id', 'not in', tracked.ids)])
        vals_list = []
        for st_line in st_lines:
            _liquidity, suspense_lines, _other = st_line._seek_for_lines()
            if not suspense_lines:
                continue
            vals_list.append(st_line._prepare_pos_cash_move_vals())
        return self.sudo().create(vals_list)

    @api.model
    def action_scan(self):
        moves = self._sync_from_statement_lines()
        if moves:
            message = _('%s new cash in/out to classify.', len(moves))
        else:
            message = _('No new cash in/out found. Everything is up to date.')
        return self.env['cash.difference.reconciliation']._notify(_('Scan Complete'), message,
                                                                    'success' if moves else 'info')

    @api.model
    def _cron_sync_pos_cash(self):
        self._sync_from_statement_lines()
        Difference = self.env['cash.difference.reconciliation']
        lines, _journals = Difference._find_new_difference_lines()
        Difference._create_from_lines(lines)

    # -------------------------------------------------------------------------
    # CLASSIFICATION
    # -------------------------------------------------------------------------

    def _rewrite_counterpart(self, account, partner=None):
        """Point the statement line's counterpart to ``account`` (or back to
        the suspense account when ``account`` is empty), the same way Odoo
        undoes a bank reconciliation."""
        self.ensure_one()
        st_line = self.statement_line_id.with_context(force_delete=True, skip_readonly_check=True)
        self._unreconcile_lines(st_line.line_ids)
        partner = partner or self.env['res.partner']
        if st_line.partner_id != partner:
            st_line.write({'partner_id': partner.id})
        st_line.write({
            'line_ids': [Command.clear()] + [
                Command.create(vals)
                for vals in st_line._prepare_move_line_default_vals(counterpart_account_id=account.id or None)
            ],
        })

    def action_classify(self):
        for move in self:
            if move.state == 'classified':
                continue
            account = move._get_classification_account()
            _liquidity, suspense_lines, _other = move.statement_line_id._seek_for_lines()
            if suspense_lines.matched_debit_ids or suspense_lines.matched_credit_ids:
                raise UserError(_('"%s" was already reconciled in Accounting.', move.name))
            move._rewrite_counterpart(account, move._get_classification_partner())
            _liquidity, _suspense, other_lines = move.statement_line_id._seek_for_lines()
            move._reconcile_with_bill(other_lines)
            move.write({
                'state': 'classified',
                'classified_by_id': self.env.user.id,
                'classified_date': fields.Datetime.now(),
            })
        return True

    def action_reset(self):
        """Send the move back to the suspense account to classify it again."""
        for move in self.filtered(lambda m: m.state == 'classified'):
            move._rewrite_counterpart(self.env['account.account'])
            move.write({
                'state': 'to_classify',
                'classified_at_pos': False,
                'classified_by_id': False,
                'classified_date': False,
            })
        return True

    def write(self, vals):
        locked_fields = {'category_id', 'classification_type', 'partner_id', 'partner_account_id', 'bill_id'}
        if locked_fields & set(vals) and any(m.state == 'classified' for m in self):
            if not self.env.context.get('ecc_allow_category_change'):
                raise UserError(_('Reset the cash move to "To Classify" before changing where it goes.'))
        return super().write(vals)

    def action_view_journal_entry(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entry'),
            'res_model': 'account.move',
            'res_id': self.account_move_id.id,
            'view_mode': 'form',
        }


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    def _prepare_pos_cash_move_vals(self, category=None):
        self.ensure_one()
        reason = self.payment_ref or ''
        session = self.pos_session_id
        # The POS builds the label as "<session>-<type>-<reason>".
        prefix = '%s-' % session.name
        if reason.startswith(prefix):
            reason = reason[len(prefix):].split('-', 1)[-1]
        return {
            'name': reason or session.name,
            'statement_line_id': self.id,
            'session_id': session.id,
            'user_id': self.create_uid.id,
            'category_id': category.id if category else False,
            'state': 'classified' if category else 'to_classify',
            'classified_at_pos': bool(category),
            'classified_by_id': self.create_uid.id if category else False,
            'classified_date': fields.Datetime.now() if category else False,
        }
