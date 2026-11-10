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
    late_entry = fields.Boolean(
        'Recorded After Closing', readonly=True, copy=False,
        help='A cash-out the cashier forgot to record, added from the session review. '
             'It lowered the expected cash and the cash difference of the session was posted again.')
    late_entry_by_id = fields.Many2one('res.users', string='Added By', readonly=True, copy=False)

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

    def action_open_split(self):
        """Split one cash in / out that holds several things (e.g. "repair 25,000 + shift pay 30,000")."""
        self.ensure_one()
        self._check_splittable()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Split %s', self.name),
            'res_model': 'ecc.cash.move.split',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_cash_move_id': self.id},
        }

    def _check_splittable(self):
        self.ensure_one()
        if self.session_id.cash_review_state == 'reviewed':
            raise UserError(_('Session %s is already reviewed. Reopen the review to split it.', self.session_id.name))
        if 'owner_move_ids' in self._fields and self.owner_move_ids:
            raise UserError(_('"%s" was collected by an owner: it cannot be split.', self.name))
        _liquidity, suspense, other = self.statement_line_id._seek_for_lines()
        if (suspense | other).filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids):
            raise UserError(_('"%s" was already reconciled in Accounting.', self.name))

    def _ecc_split(self, parts):
        """``parts``: [(description, amount, category or None)], amounts positive and adding up to this move.
        This move keeps the first part; the others become cash in / out of the same session on the same day
        (the cash of the session does not change). Parts with a category are classified with it."""
        self.ensure_one()
        self._check_splittable()
        currency = self.currency_id or self.company_id.currency_id
        if len(parts) < 2:
            raise UserError(_('Split it in at least two parts.'))
        if any(currency.compare_amounts(amount, 0.0) <= 0 for _name, amount, _cat in parts):
            raise UserError(_('Every part needs a positive amount.'))
        total = sum(amount for _name, amount, _cat in parts)
        if currency.compare_amounts(total, self.amount_abs):
            raise UserError(_('The parts add up to %(total)s; the cash-out is %(amount)s.',
                              total=currency.format(total), amount=currency.format(self.amount_abs)))
        if self.state == 'classified':
            self.action_reset()
        sign = -1 if self.move_type == 'out' else 1
        kind = _('out') if self.move_type == 'out' else _('in')
        session = self.session_id
        st_line = self.statement_line_id.with_context(skip_readonly_check=True)
        original = self.name
        (name, amount, category), rest = parts[0], parts[1:]
        name = (name or '').strip() or original
        st_line.write({'amount': sign * amount, 'payment_ref': '%s-%s-%s' % (session.name, kind, name)})
        self.write({'name': name, 'category_id': category.id if category else False,
                    'classification_type': 'category'})
        if category:
            self.action_classify()
        moves = self
        for name, amount, category in rest:
            name = (name or '').strip() or original
            new_line = self.env['account.bank.statement.line'].sudo().with_company(self.company_id).create({
                'journal_id': st_line.journal_id.id,
                'amount': sign * amount,
                'date': st_line.date,
                'pos_session_id': session.id,
                'payment_ref': '%s-%s-%s' % (session.name, kind, name),
                'counterpart_account_id': category.account_id.id if category else False,
            })
            vals = new_line._prepare_pos_cash_move_vals(category=category)
            vals.update({'user_id': self.user_id.id, 'classified_at_pos': False, 'name': name})
            moves |= self.sudo().create(vals)
        session.message_post(body=_('Cash %(kind)s "%(name)s" (%(amount)s) split in %(count)s: %(parts)s.',
                                    kind=kind, name=original, amount=currency.format(total), count=len(parts),
                                    parts=', '.join('%s %s' % (n or original, currency.format(a))
                                                    for n, a, _c in parts)))
        return moves

    def action_remove_late_entry(self):
        """Undo a forgotten expense added after closing: the expected cash and the difference come back."""
        for move in self:
            if not move.late_entry:
                raise UserError(_('Only cash-outs recorded after closing can be removed here.'))
            session = move.session_id
            session._ecc_check_can_correct()
            amount = move.amount
            st_line = move.statement_line_id
            if move.state == 'classified':
                move.action_reset()   # also undoes what the classification did (bill, owner box...)
            self._unreconcile_lines(st_line.line_ids)
            session.message_post(body=_('Forgotten expense removed: %(name)s (%(amount)s).',
                                        name=move.name, amount=session.currency_id.format(abs(amount))))
            move.sudo().unlink()
            st_line.sudo().unlink()
            session.sudo().cash_real_transaction -= amount
            session._ecc_redo_cash_difference()
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
