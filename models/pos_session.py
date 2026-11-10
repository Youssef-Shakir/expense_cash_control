# -*- coding: utf-8 -*-
from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError


class PosSession(models.Model):
    _inherit = 'pos.session'

    cash_move_ids = fields.One2many('pos.cash.move', 'session_id', string='Cash In/Out')
    cash_difference_ids = fields.One2many('cash.difference.reconciliation', 'session_id', string='Cash Differences')

    cash_in_total = fields.Monetary('Total Cash In', compute='_compute_cash_review_stats', currency_field='currency_id')
    cash_out_total = fields.Monetary('Total Cash Out', compute='_compute_cash_review_stats', currency_field='currency_id')
    cash_to_classify_count = fields.Integer('Cash Moves to Classify', compute='_compute_cash_review_stats')
    cash_difference_pending_count = fields.Integer('Differences to Classify', compute='_compute_cash_review_stats')

    has_card_methods = fields.Boolean(compute='_compute_card_closing')
    card_expected_total = fields.Monetary(
        'Card Expected', compute='_compute_card_closing', currency_field='currency_id',
        help='Card / bank payments registered in the POS during the session.')
    card_counted_total = fields.Monetary(
        'Card Counted', compute='_compute_card_closing', currency_field='currency_id',
        help='What was counted on the card terminal at closing (expected + card difference).')
    card_difference = fields.Monetary(
        'Card Difference', compute='_compute_card_closing', currency_field='currency_id',
        help='Counted minus expected on the card / bank payment methods (positive = gain).')
    total_difference = fields.Monetary(
        'Net Difference', compute='_compute_card_closing', currency_field='currency_id',
        help='Cash difference + card difference. When an order paid in cash is registered as card '
             '(or the opposite) the two differences cancel out here.')
    differences_offset = fields.Boolean(compute='_compute_card_closing')

    cash_review_state = fields.Selection([
        ('to_review', 'To Review'),
        ('reviewed', 'Reviewed'),
    ], string='Cash Review', copy=False, tracking=True, index=True,
        help='Set to "To Review" when the session is closed.')
    cash_reviewed_by_id = fields.Many2one('res.users', string='Reviewed By', readonly=True, copy=False)
    cash_reviewed_date = fields.Datetime('Reviewed On', readonly=True, copy=False)
    cash_review_note = fields.Text('Review Notes', copy=False)

    @api.depends('cash_move_ids.amount', 'cash_move_ids.state', 'cash_difference_ids.state')
    def _compute_cash_review_stats(self):
        for session in self:
            moves = session.cash_move_ids
            session.cash_in_total = sum(moves.filtered(lambda m: m.amount > 0).mapped('amount'))
            session.cash_out_total = -sum(moves.filtered(lambda m: m.amount < 0).mapped('amount'))
            session.cash_to_classify_count = len(moves.filtered(lambda m: m.state == 'to_classify'))
            session.cash_difference_pending_count = len(
                session.cash_difference_ids.filtered(lambda d: d.state == 'pending'))

    @api.depends('cash_difference_ids.amount', 'cash_difference_ids.difference_type',
                 'cash_difference_ids.source', 'cash_register_difference', 'state')
    def _compute_card_closing(self):
        Difference = self.env['cash.difference.reconciliation']
        expected = {}
        card_methods = Difference._card_methods(self)
        if card_methods and self.ids:
            for session, amount in self.env['pos.payment'].sudo()._read_group(
                    [('session_id', 'in', self.ids), ('payment_method_id', 'in', card_methods.ids)],
                    ['session_id'], ['amount:sum']):
                expected[session.id] = amount
        for session in self:
            card = session.cash_difference_ids.filtered(lambda d: d.source == 'card')
            diff = sum(d.amount if d.difference_type == 'gain' else -d.amount for d in card)
            cash_diff = session.cash_register_difference if session.state == 'closed' else 0.0
            session.has_card_methods = bool(Difference._card_methods(session))
            session.card_expected_total = expected.get(session.id, 0.0)
            session.card_counted_total = session.card_expected_total + diff
            session.card_difference = diff
            session.total_difference = cash_diff + diff
            currency = session.currency_id
            session.differences_offset = bool(
                currency and not currency.is_zero(diff) and not currency.is_zero(cash_diff)
                and (diff > 0) != (cash_diff > 0))

    # -------------------------------------------------------------------------
    # POS: categorized cash in / out
    # -------------------------------------------------------------------------

    def _prepare_account_bank_statement_line_vals(self, session, sign, amount, reason, extras):
        vals = super()._prepare_account_bank_statement_line_vals(session, sign, amount, reason, extras)
        category = self._get_cash_category_from_extras(session, extras)
        if category:
            vals['counterpart_account_id'] = category.account_id.id
        return vals

    def _get_cash_category_from_extras(self, session, extras):
        category_id = (extras or {}).get('expense_category_id')
        if not category_id or not session.config_id.use_cash_categories:
            return self.env['expense.category']
        category = self.env['expense.category'].sudo().browse(int(category_id)).exists()
        if category and not category.account_id:
            raise UserError(_('The cash category "%s" has no account.', category.name))
        return category

    def try_cash_in_out(self, _type, amount, reason, extras):
        StLine = self.env['account.bank.statement.line']
        last_id = StLine.search([], order='id desc', limit=1).id or 0
        result = super().try_cash_in_out(_type, amount, reason, extras)
        new_lines = StLine.search([('id', '>', last_id), ('pos_session_id', 'in', self.ids)])
        vals_list = []
        for st_line in new_lines:
            category = self._get_cash_category_from_extras(st_line.pos_session_id, extras)
            vals_list.append(st_line._prepare_pos_cash_move_vals(category=category))
        self.env['pos.cash.move'].sudo().create(vals_list)
        return result

    # -------------------------------------------------------------------------
    # Closing & review
    # -------------------------------------------------------------------------

    def _validate_session(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        result = super()._validate_session(balancing_account, amount_to_balance, bank_payment_method_diffs)
        closed = self.filtered(lambda s: s.state == 'closed')
        if closed:
            closed._prepare_cash_review()
        return result

    def _prepare_cash_review(self):
        """Collect the session's cash in/out and differences for the manager review."""
        self.env['pos.cash.move'].sudo()._sync_from_statement_lines(self)
        Difference = self.env['cash.difference.reconciliation'].sudo()
        lines, _journals = Difference._find_new_difference_lines(self)
        Difference._create_from_lines(lines)
        self.filtered(lambda s: s.cash_journal_id and not s.cash_review_state).sudo().cash_review_state = 'to_review'

    def action_cash_review_done(self):
        for session in self:
            if session.state != 'closed':
                raise UserError(_('Session %s is not closed yet.', session.name))
            if session.cash_to_classify_count or session.cash_difference_pending_count:
                raise UserError(_(
                    'Session %(session)s still has %(moves)s cash in/out and %(diffs)s cash difference(s) to classify.',
                    session=session.name, moves=session.cash_to_classify_count,
                    diffs=session.cash_difference_pending_count))
        self.write({
            'cash_review_state': 'reviewed',
            'cash_reviewed_by_id': self.env.user.id,
            'cash_reviewed_date': fields.Datetime.now(),
        })
        return True

    def action_cash_review_reopen(self):
        self.write({'cash_review_state': 'to_review', 'cash_reviewed_by_id': False, 'cash_reviewed_date': False})
        return True

    def action_cash_review_refresh(self):
        self._prepare_cash_review()
        return True

    # -------------------------------------------------------------------------
    # Corrections after closing: forgotten expenses
    # -------------------------------------------------------------------------

    def _ecc_check_can_correct(self):
        for session in self:
            if session.state != 'closed':
                raise UserError(_('Session %s is not closed: record the expense in the POS.', session.name))
            if not session.cash_journal_id:
                raise UserError(_('Session %s has no cash drawer.', session.name))
            if session.cash_review_state == 'reviewed':
                raise UserError(_('Session %s is already reviewed. Reopen the review to correct it.', session.name))

    def _ecc_add_late_expense(self, name, amount, category=None):
        """A cash-out paid from the drawer during the session that the cashier forgot to record.

        The money already left the drawer, so the counted cash (and the cash to collect) does not
        change: the expected cash goes down by ``amount`` and the cash difference is posted again.
        Without ``category`` the cash-out waits on the suspense account to be classified like any
        uncategorized POS cash-out.
        """
        self.ensure_one()
        self._ecc_check_can_correct()
        currency = self.currency_id
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_('The amount must be positive.'))
        if category and not category.account_id:
            raise UserError(_('The category "%s" has no account.', category.name))
        name = (name or '').strip() or (category.name if category else _('Forgotten expense'))
        st_line = self.env['account.bank.statement.line'].sudo().with_company(self.company_id).create({
            'journal_id': self.cash_journal_id.id,
            'amount': -amount,
            'date': self._ecc_closing_date(),
            'pos_session_id': self.id,
            'payment_ref': '%s-%s-%s' % (self.name, _('out'), name),
            'counterpart_account_id': category.account_id.id if category else False,
        })
        vals = st_line._prepare_pos_cash_move_vals(category=category)
        vals.update({
            'user_id': self.env.user.id,
            'classified_at_pos': False,
            'late_entry': True,
            'late_entry_by_id': self.env.user.id,
        })
        move = self.env['pos.cash.move'].sudo().create(vals)
        self.sudo().cash_real_transaction -= amount
        before, after = self._ecc_redo_cash_difference()
        self.message_post(body=_(
            'Forgotten expense recorded after closing: %(name)s (%(amount)s). '
            'Difference %(before)s → %(after)s.',
            name=name, amount=currency.format(amount),
            before=currency.format(before), after=currency.format(after)))
        return move

    def _ecc_closing_date(self):
        self.ensure_one()
        lines = self.sudo().statement_line_ids.sorted('date')
        if lines:
            return lines[-1].date
        return fields.Date.context_today(self, self.stop_at) if self.stop_at else fields.Date.context_today(self)

    def _ecc_cash_difference_lines(self):
        """The statement lines Odoo posted for the counted cash difference of the session."""
        self.ensure_one()
        journal = self.cash_journal_id
        accounts = journal.loss_account_id | journal.profit_account_id
        tracked = self.env['pos.cash.move'].sudo().search([('session_id', '=', self.id)]).statement_line_id
        return self.sudo().statement_line_ids.filtered(
            lambda l: l not in tracked and l.line_ids.account_id & accounts)

    def _ecc_redo_cash_difference(self):
        """Post the cash difference again from the (corrected) expected cash.

        The old difference entry is removed with its difference record (a classified one is reset
        first, its correcting entry cancelled), then the new difference is posted and collected for
        the review. Returns (old difference, new difference).
        """
        self.ensure_one()
        currency = self.currency_id
        old_lines = self._ecc_cash_difference_lines()
        old = sum(old_lines.mapped('amount'))
        self.invalidate_recordset(['cash_register_balance_end', 'cash_register_difference'])
        new = currency.round(self.cash_register_difference)
        if currency.compare_amounts(old, new) == 0:
            return old, new
        journal = self.cash_journal_id
        account = journal.loss_account_id if new < 0 else journal.profit_account_id
        if not currency.is_zero(new) and not account:
            raise UserError(_('Please define a Loss and a Profit Account on the %s journal.', journal.name))
        date = old_lines[:1].date or self._ecc_closing_date()

        Difference = self.env['cash.difference.reconciliation'].sudo()
        records = Difference.search([('original_move_id', 'in', old_lines.move_id.ids)])
        records.filtered(lambda r: r.state == 'classified').action_reset()
        records.unlink()
        Difference._unreconcile_lines(old_lines.line_ids)
        old_lines.unlink()

        if not currency.is_zero(new):
            self.env['account.bank.statement.line'].sudo().with_company(self.company_id).create({
                'journal_id': journal.id,
                'amount': new,
                'date': date,
                'pos_session_id': self.id,
                'payment_ref': _('Cash difference observed during the counting (%(kind)s) - corrected after closing',
                                 kind=_('Loss') if new < 0 else _('Profit')),
                'counterpart_account_id': account.id,
            })
            lines, _journals = Difference._find_new_difference_lines(self)
            Difference._create_from_lines(lines)
        self.invalidate_recordset(['cash_register_balance_end', 'cash_register_difference'])
        return old, new

    # -------------------------------------------------------------------------
    # Corrections after closing: forgotten card difference
    # -------------------------------------------------------------------------

    def _ecc_card_outstanding_account(self, method):
        """Account the card payments of ``method`` wait on until the bank pays them (like Odoo's closing)."""
        self.ensure_one()
        payments = self.env['account.payment'].sudo().search(
            [('pos_session_id', '=', self.id), ('pos_payment_method_id', '=', method.id)], limit=1)
        journal = method.journal_id
        return (payments.outstanding_account_id or method.outstanding_account_id
                or journal.inbound_payment_method_line_ids.payment_account_id[:1]
                or journal.default_account_id)

    def _ecc_add_card_difference(self, method, amount, difference_type, reason=None):
        """A card difference the cashier did not count at closing, e.g. an order paid by card but rung up
        as cash: the drawer is short (cash loss) and the card terminal got more (card gain). Posted like Odoo
        posts a counted card difference, and listed with the session's differences to classify: with the
        same category, the cash loss and the card gain cancel out."""
        self.ensure_one()
        if self.state != 'closed':
            raise UserError(_('Session %s is not closed.', self.name))
        if self.cash_review_state == 'reviewed':
            raise UserError(_('Session %s is already reviewed. Reopen the review to correct it.', self.name))
        currency = self.currency_id
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_('The amount must be positive.'))
        Difference = self.env['cash.difference.reconciliation']
        if method not in Difference._card_methods(self):
            raise UserError(_('%s is not a card / bank payment method of this session.', method.name))
        journal = method.journal_id
        diff_account = journal.profit_account_id if difference_type == 'gain' else journal.loss_account_id
        if not diff_account:
            raise UserError(_('Set the profit and loss accounts of the journal %s first.', journal.name))
        card_account = self._ecc_card_outstanding_account(method)
        label = _('Card difference %(method)s: %(reason)s (%(session)s)', method=method.name,
                  reason=(reason or '').strip() or _('not counted at closing'), session=self.name)
        if difference_type == 'gain':
            debit, credit = card_account, diff_account
        else:
            debit, credit = diff_account, card_account
        entry = self.env['account.move'].sudo().with_company(self.company_id).create({
            'move_type': 'entry', 'journal_id': journal.id, 'date': self._ecc_closing_date(), 'ref': label,
            'line_ids': [
                Command.create({'name': label, 'account_id': debit.id, 'debit': amount}),
                Command.create({'name': label, 'account_id': credit.id, 'credit': amount}),
            ],
        })
        entry.action_post()
        line = entry.line_ids.filtered(lambda l: l.account_id == diff_account)
        difference = Difference.sudo().create({
            'original_move_id': entry.id, 'original_move_line_id': line.id, 'session_id': self.id,
            'source': 'card', 'payment_method_id': method.id, 'date': entry.date, 'amount': amount,
            'currency_id': currency.id, 'original_account_id': diff_account.id,
            'difference_type': difference_type, 'company_id': self.company_id.id,
            'notes': (reason or '').strip() or False,
        })
        self.message_post(body=_('Forgotten card difference recorded: %(method)s %(sign)s%(amount)s (%(reason)s).',
                                 method=method.name, sign='+' if difference_type == 'gain' else '−',
                                 amount=currency.format(amount), reason=(reason or '').strip() or '-'))
        return difference

    def action_open_late_card_difference(self):
        self.ensure_one()
        if self.cash_review_state == 'reviewed':
            raise UserError(_('Session %s is already reviewed. Reopen the review to correct it.', self.name))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Forgotten Card Difference'),
            'res_model': 'ecc.session.card.difference',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.id},
        }

    def action_open_late_expense(self):
        self.ensure_one()
        self._ecc_check_can_correct()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Forgotten Expense'),
            'res_model': 'ecc.session.late.expense',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.id},
        }

    def action_open_cash_review(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cash Review'),
            'res_model': 'pos.session',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('expense_cash_control.view_pos_session_cash_review_form').id, 'form')],
        }

    @api.model
    def _load_pos_data_models(self, config_id):
        models_to_load = super()._load_pos_data_models(config_id)
        models_to_load.append('expense.category')
        return models_to_load
