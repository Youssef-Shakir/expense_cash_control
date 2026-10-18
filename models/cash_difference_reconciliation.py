# -*- coding: utf-8 -*-
from odoo import models, fields, api, Command, _
from odoo.exceptions import UserError


class CashDifferenceReconciliation(models.Model):
    """Reconcile POS cash differences by reclassifying them to expense categories."""
    _name = 'cash.difference.reconciliation'
    _description = 'Cash Difference Reconciliation'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'ecc.cash.classification.mixin']
    _order = 'date desc, id desc'

    name = fields.Char('Reference', readonly=True, copy=False, default='New')
    original_move_id = fields.Many2one(
        'account.move', string='Original Entry', readonly=True, ondelete='restrict',
        help='The original POS cash difference journal entry')
    original_move_line_id = fields.Many2one(
        'account.move.line', string='Original Line', readonly=True, ondelete='restrict',
        help='The specific journal entry line with the cash difference')
    session_id = fields.Many2one(
        'pos.session', string='POS Session', readonly=True, index=True,
        help='The POS session closed with this difference')
    config_id = fields.Many2one(related='session_id.config_id', string='Point of Sale', store=True)
    cashier_id = fields.Many2one(related='session_id.user_id', string='Cashier', store=True)
    date = fields.Date('Date', readonly=True, help='Date of the cash difference')
    amount = fields.Monetary(
        'Amount', currency_field='currency_id', readonly=True,
        help='Amount of the cash difference (always positive)')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id, readonly=True)
    original_account_id = fields.Many2one(
        'account.account', string='Original Account', readonly=True,
        help='The loss/gain account where the difference was originally posted')
    difference_type = fields.Selection([
        ('loss', 'Cash Loss'),
        ('gain', 'Cash Gain'),
    ], string='Type', readonly=True, help='Whether this is a cash shortage (loss) or overage (gain)')
    category_id = fields.Many2one(
        'expense.category', string='Expense Category', tracking=True,
        help='Select a category to reclassify this cash difference')
    correcting_move_id = fields.Many2one(
        'account.move', string='Correcting Entry', readonly=True, copy=False,
        help='The journal entry created to reclassify this difference')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('classified', 'Classified'),
    ], string='Status', default='pending', readonly=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company, required=True, readonly=True)
    notes = fields.Text('Notes', help='Optional notes about this cash difference')

    def _get_cash_direction(self):
        self.ensure_one()
        # Missing cash went to someone; extra cash came from someone.
        return 'out' if self.difference_type == 'loss' else 'in'

    @api.model_create_multi
    def create(self, vals_list):
        """Generate reference sequence on create."""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('cash.difference.reconciliation') or 'CDR/0001'
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # DETECTION
    # -------------------------------------------------------------------------

    @api.model
    def _find_new_difference_lines(self, sessions=None):
        """Journal items posted on the cash journals' loss/profit accounts.

        POS differences are found through their session (the label is written
        in the language of whoever closed the session, so it can't be trusted);
        other cash journal differences are still found by their label.
        """
        journal_domain = [('type', '=', 'cash')]
        if sessions is None:
            journal_domain.append(('company_id', 'in', self.env.companies.ids))
        else:
            journal_domain.append(('id', 'in', sessions.cash_journal_id.ids))
        cash_journals = self.env['account.journal'].search(journal_domain)
        target_accounts = cash_journals.loss_account_id | cash_journals.profit_account_id
        if not target_accounts:
            return self.env['account.move.line'], cash_journals

        existing_line_ids = self.with_context(active_test=False).search([]).original_move_line_id.ids
        domain = [
            ('account_id', 'in', target_accounts.ids),
            ('parent_state', '=', 'posted'),
            ('id', 'not in', existing_line_ids),
        ]
        if sessions is not None:
            domain.append(('move_id.statement_line_id.pos_session_id', 'in', sessions.ids))
        else:
            domain += [
                '|', '|',
                ('move_id.statement_line_id.pos_session_id', '!=', False),
                ('name', 'ilike', 'cash difference'),
                ('move_id.ref', 'ilike', 'cash difference'),
            ]
        return self.env['account.move.line'].search(domain), cash_journals

    @api.model
    def _create_from_lines(self, move_lines):
        vals_list = []
        for line in move_lines:
            # Loss: money is missing, posted as debit on the loss account.
            # Gain: extra money, posted as credit on the profit account.
            vals_list.append({
                'original_move_id': line.move_id.id,
                'original_move_line_id': line.id,
                'session_id': line.move_id.statement_line_id.pos_session_id.id,
                'date': line.date,
                'amount': line.debit or line.credit,
                'currency_id': line.company_currency_id.id,
                'original_account_id': line.account_id.id,
                'difference_type': 'loss' if line.debit > 0 else 'gain',
                'company_id': line.company_id.id,
            })
        return self.create(vals_list)

    @api.model
    def action_detect_cash_differences(self):
        """Scan for unprocessed cash differences and create records for them."""
        move_lines, cash_journals = self._find_new_difference_lines()
        if not cash_journals:
            return self._notify(_('Configuration Required'),
                                _('No cash journals found. Please configure a cash journal first.'), 'warning', sticky=True)
        if not (cash_journals.loss_account_id | cash_journals.profit_account_id):
            return self._notify(_('Configuration Required'),
                                _('No loss/profit accounts configured on cash journals. Please configure them first.'),
                                'warning', sticky=True)
        if not move_lines:
            return self._notify(_('Scan Complete'), _('No new cash differences found. All entries are up to date.'), 'info')

        records = self._create_from_lines(move_lines)
        currency = self.env.company.currency_id
        losses = records.filtered(lambda r: r.difference_type == 'loss')
        gains = records - losses
        parts = []
        if losses:
            parts.append(_('%(count)s loss(es) totaling %(amount)s',
                           count=len(losses), amount=currency.format(sum(losses.mapped('amount')))))
        if gains:
            parts.append(_('%(count)s gain(s) totaling %(amount)s',
                           count=len(gains), amount=currency.format(sum(gains.mapped('amount')))))
        return self._notify(_('Scan Complete'), _('Found: %s. Ready for classification.', ', '.join(parts)), 'success')

    @api.model
    def _notify(self, title, message, notif_type, sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': sticky,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    # -------------------------------------------------------------------------
    # CLASSIFICATION
    # -------------------------------------------------------------------------

    def _get_reclassification_journal(self):
        self.ensure_one()
        journal = self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        return journal or self.original_move_id.journal_id

    def _classify(self):
        """Create the correcting entry moving the difference to the category or partner account."""
        for record in self:
            if record.state == 'classified':
                raise UserError(_('%s has already been classified.', record.name))
            target_account = record._get_classification_account()
            partner = record._get_classification_partner()
            label = record._get_classification_label()

            # LOSS: debit target account, credit loss account.
            # GAIN: debit gain account, credit target account.
            if record.difference_type == 'loss':
                debit_account, credit_account = target_account, record.original_account_id
                description = _('Reclassify cash loss: %s', label)
            else:
                debit_account, credit_account = record.original_account_id, target_account
                description = _('Reclassify cash gain: %s', label)

            move = self.env['account.move'].create({
                'move_type': 'entry',
                'date': fields.Date.context_today(record),
                'ref': _('Reclassification of %s', record.name),
                'journal_id': record._get_reclassification_journal().id,
                'company_id': record.company_id.id,
                'partner_id': partner.id,
                'line_ids': [
                    Command.create({
                        'name': description,
                        'account_id': debit_account.id,
                        'partner_id': partner.id if debit_account == target_account else False,
                        'debit': record.amount,
                        'credit': 0.0,
                    }),
                    Command.create({
                        'name': description,
                        'account_id': credit_account.id,
                        'partner_id': partner.id if credit_account == target_account else False,
                        'debit': 0.0,
                        'credit': record.amount,
                    }),
                ],
            })
            move.action_post()
            record._reconcile_with_bill(move.line_ids)
            record.write({'correcting_move_id': move.id, 'state': 'classified'})

    def action_classify(self):
        """Classify the selected cash differences (form button or list action)."""
        self._classify()
        if len(self) == 1:
            message = _('Cash difference successfully reclassified to "%s".', self._get_classification_label())
        else:
            message = _('%s cash differences reclassified.', len(self))
        return self._notify(_('Classified'), message, 'success')

    def action_reset(self):
        """Cancel the correcting entry so the difference can be classified again."""
        for record in self.filtered(lambda r: r.state == 'classified'):
            if record.correcting_move_id:
                self._unreconcile_lines(record.correcting_move_id.line_ids)
                record.correcting_move_id.button_draft()
                record.correcting_move_id.button_cancel()
            record.write({'state': 'pending', 'correcting_move_id': False})

    def action_view_original_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Original Entry'),
            'res_model': 'account.move',
            'res_id': self.original_move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_correcting_move(self):
        self.ensure_one()
        if not self.correcting_move_id:
            raise UserError(_('No correcting entry has been created yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Correcting Entry'),
            'res_model': 'account.move',
            'res_id': self.correcting_move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
