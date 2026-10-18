# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PosSession(models.Model):
    _inherit = 'pos.session'

    cash_move_ids = fields.One2many('pos.cash.move', 'session_id', string='Cash In/Out')
    cash_difference_ids = fields.One2many('cash.difference.reconciliation', 'session_id', string='Cash Differences')

    cash_in_total = fields.Monetary('Total Cash In', compute='_compute_cash_review_stats', currency_field='currency_id')
    cash_out_total = fields.Monetary('Total Cash Out', compute='_compute_cash_review_stats', currency_field='currency_id')
    cash_to_classify_count = fields.Integer('Cash Moves to Classify', compute='_compute_cash_review_stats')
    cash_difference_pending_count = fields.Integer('Differences to Classify', compute='_compute_cash_review_stats')

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
