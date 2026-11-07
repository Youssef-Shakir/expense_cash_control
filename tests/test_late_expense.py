# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ExpenseCashCommon


@tagged('post_install', '-at_install')
class TestLateExpense(ExpenseCashCommon):
    """Forgotten expenses recorded after closing correct the expected cash and the cash difference."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['account.account']
        cls.loss_account = Account.create({'name': 'ECC Late Loss', 'code': 'ECC6997', 'account_type': 'expense'})
        cls.gain_account = Account.create({'name': 'ECC Late Gain', 'code': 'ECC7997', 'account_type': 'income_other'})
        cls.cash_journal.write({'loss_account_id': cls.loss_account.id, 'profit_account_id': cls.gain_account.id})
        cls.cash_method = cls.env['pos.payment.method'].create({'name': 'ECC Cash', 'journal_id': cls.cash_journal.id})
        cls.config = cls.env['pos.config'].create({
            'name': 'ECC Late POS', 'payment_method_ids': [(6, 0, cls.cash_method.ids)]})

    def _closed_session(self, cash_in, counted):
        session = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        session.set_opening_control(0, '')
        session.try_cash_in_out('in', cash_in, 'float', {'translatedType': 'in', 'formattedAmount': str(cash_in)})
        session.post_closing_cash_details(counted)
        session.close_session_from_ui()
        self.assertEqual(session.state, 'closed')
        session.cash_move_ids.category_id = self.category_in
        session.cash_move_ids.action_classify()
        return session

    def _journal_balance(self):
        return sum(self.env['account.move.line'].search([
            ('account_id', '=', self.cash_journal.default_account_id.id),
            ('parent_state', '=', 'posted')]).mapped('balance'))

    def _cash_diffs(self, session):
        return session.cash_difference_ids.filtered(lambda d: d.source == 'cash')

    def test_forgotten_expense_clears_loss(self):
        session = self._closed_session(100.0, 60.0)
        self.assertAlmostEqual(session.cash_register_difference, -40.0)
        balance = self._journal_balance()

        wizard = self.env['ecc.session.late.expense'].create({
            'session_id': session.id, 'name': 'Vegetables', 'amount': 40.0, 'category_id': self.category.id})
        self.assertAlmostEqual(wizard.expected_after, 60.0)
        self.assertAlmostEqual(wizard.difference_after, 0.0)
        wizard.action_confirm()

        self.assertAlmostEqual(session.cash_register_balance_end, 60.0)
        self.assertAlmostEqual(session.cash_register_balance_end_real, 60.0, msg='counted cash never changes')
        self.assertAlmostEqual(session.cash_register_difference, 0.0)
        self.assertFalse(self._cash_diffs(session), 'no difference left to classify')
        move = session.cash_move_ids.filtered('late_entry')
        self.assertEqual((move.state, move.category_id, move.amount, move.name),
                         ('classified', self.category, -40.0, 'Vegetables'))
        self.assertAlmostEqual(self._journal_balance(), balance, msg='the drawer balance stays the counted cash')
        self.assertEqual(sum(self.env['account.move.line'].search([
            ('account_id', '=', self.loss_account.id), ('parent_state', '=', 'posted')]).mapped('balance')), 0.0)

    def test_classified_difference_redone_and_flip_to_gain(self):
        session = self._closed_session(100.0, 60.0)
        diff = self._cash_diffs(session)
        diff.category_id = self.category
        diff.action_classify()
        correcting = diff.correcting_move_id

        session._ecc_add_late_expense('Gas', 30.0)   # no category: waits to be classified
        self.assertEqual(correcting.state, 'cancel', 'the old classification is undone')
        diff = self._cash_diffs(session)
        self.assertEqual((diff.difference_type, diff.amount, diff.state), ('loss', 10.0, 'pending'))
        late = session.cash_move_ids.filtered('late_entry')
        self.assertEqual(late.state, 'to_classify')
        self.assertEqual(session.cash_to_classify_count, 1)

        session._ecc_add_late_expense('Ice', 50.0, self.category)
        diff = self._cash_diffs(session)
        self.assertEqual((diff.difference_type, diff.amount), ('gain', 40.0))
        self.assertAlmostEqual(session.cash_register_difference, 40.0)

        # A mistake: remove the 50 again -> back to a 10 loss.
        session.cash_move_ids.filtered(lambda m: m.name == 'Ice').action_remove_late_entry()
        diff = self._cash_diffs(session)
        self.assertEqual((diff.difference_type, diff.amount), ('loss', 10.0))
        self.assertAlmostEqual(session.cash_register_balance_end, 70.0)
        self.assertEqual(len(session.cash_move_ids.filtered('late_entry')), 1)

    def test_admin_report_follows_correction(self):
        if 'pos_admin_session_report' not in self.env.registry._init_modules:
            self.skipTest('pos_admin_session_report not installed')
        session = self._closed_session(100.0, 60.0)
        session._ecc_add_late_expense('Vegetables', 25.0, self.category)
        closing = self.env['pos.session']._report_closing(session)
        cash = next(m for m in closing['methods'] if m['is_cash'])
        self.assertAlmostEqual(cash['expected'], 75.0)
        self.assertAlmostEqual(cash['counted'], 60.0)
        self.assertAlmostEqual(cash['difference'], -15.0)

    def test_reviewed_or_open_session_refused(self):
        session = self._closed_session(100.0, 100.0)
        session.action_cash_review_done()
        with self.assertRaises(UserError):
            session._ecc_add_late_expense('Late', 5.0, self.category)
        session.action_cash_review_reopen()
        session._ecc_add_late_expense('Late', 5.0, self.category)
        self.assertAlmostEqual(session.cash_register_difference, 5.0)

        open_session = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        with self.assertRaises(UserError):
            open_session._ecc_add_late_expense('Late', 5.0, self.category)
