# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ExpenseCashCommon


@tagged('post_install', '-at_install')
class TestPosCash(ExpenseCashCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['account.account']
        cls.cash_journal.write({
            'loss_account_id': Account.create({
                'name': 'ECC Cash Loss', 'code': 'ECC6999', 'account_type': 'expense'}).id,
            'profit_account_id': Account.create({
                'name': 'ECC Cash Gain', 'code': 'ECC7999', 'account_type': 'income_other'}).id,
        })
        cls.cash_method = cls.env['pos.payment.method'].create({
            'name': 'ECC Cash', 'journal_id': cls.cash_journal.id,
        })
        cls.config = cls.env['pos.config'].create({
            'name': 'ECC Test POS',
            'payment_method_ids': [(6, 0, cls.cash_method.ids)],
        })

    def _open_session(self):
        session = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        session.set_opening_control(0, '')
        return session

    def _cash_move(self, session, move_type, amount, reason, category=None):
        extras = {'translatedType': move_type, 'formattedAmount': str(amount)}
        if category:
            extras['expense_category_id'] = category.id
        session.try_cash_in_out(move_type, amount, reason, extras)
        return session.cash_move_ids.sorted('id')[-1:]

    def _close(self, session, counted):
        session.post_closing_cash_details(counted)
        session.close_session_from_ui()
        self.assertEqual(session.state, 'closed')

    def test_uncategorized_cash_out_waits_on_suspense(self):
        session = self._open_session()
        move = self._cash_move(session, 'out', 30.0, 'bought ice')
        self.assertEqual(move.state, 'to_classify')
        self.assertEqual(move.move_type, 'out')
        self.assertEqual(move.amount_abs, 30.0)
        self.assertEqual(move.name, 'bought ice')
        _liq, suspense, _other = move.statement_line_id._seek_for_lines()
        self.assertTrue(suspense, 'Uncategorized cash out stays on the suspense account')

        move.category_id = self.category
        move.action_classify()
        self.assertEqual(move.state, 'classified')
        _liq, suspense, other = move.statement_line_id._seek_for_lines()
        self.assertFalse(suspense)
        self.assertEqual(other.account_id, self.expense_account)
        self.assertEqual(other.debit, 30.0)
        self.assertTrue(move.statement_line_id.is_reconciled)

        move.action_reset()
        self.assertEqual(move.state, 'to_classify')
        _liq, suspense, _other = move.statement_line_id._seek_for_lines()
        self.assertTrue(suspense)

    def test_categorized_at_pos(self):
        self.config.use_cash_categories = True
        session = self._open_session()
        move = self._cash_move(session, 'in', 100.0, 'owner', category=self.category_in)
        self.assertEqual(move.state, 'classified')
        self.assertTrue(move.classified_at_pos)
        self.assertEqual(move.category_id, self.category_in)
        _liq, suspense, other = move.statement_line_id._seek_for_lines()
        self.assertFalse(suspense)
        self.assertEqual(other.account_id, self.income_account)

    def test_category_ignored_when_feature_off(self):
        session = self._open_session()
        move = self._cash_move(session, 'out', 10.0, 'x', category=self.category)
        self.assertEqual(move.state, 'to_classify')

    def test_close_session_collects_and_review(self):
        session = self._open_session()
        self._cash_move(session, 'out', 20.0, 'gas')
        # expected cash: 0 - 20 = -20; counted -25 -> 5 loss
        self._close(session, -25.0)
        self.assertEqual(session.cash_review_state, 'to_review')
        self.assertEqual(session.cash_to_classify_count, 1)
        diff = session.cash_difference_ids
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff.difference_type, 'loss')
        self.assertAlmostEqual(diff.amount, 5.0)

        with self.assertRaises(UserError):
            session.action_cash_review_done()

        session.cash_move_ids.category_id = self.category
        session.cash_move_ids.action_classify()
        diff.category_id = self.category
        diff.action_classify()
        self.assertEqual(diff.state, 'classified')
        self.assertEqual(diff.correcting_move_id.journal_id.type, 'general')
        session.action_cash_review_done()
        self.assertEqual(session.cash_review_state, 'reviewed')
        self.assertEqual(session.cash_reviewed_by_id, self.env.user)

    def test_difference_found_in_any_language(self):
        """Detection must not depend on the (translated) label of the closing line."""
        session = self._open_session()
        self._close(session, 7.0)
        st_line = session.statement_line_ids.filtered(lambda l: l.amount == 7.0)
        st_line.move_id.line_ids.write({'name': 'فرق النقد'})
        session.cash_difference_ids.unlink()
        lines, _journals = self.env['cash.difference.reconciliation']._find_new_difference_lines(session)
        self.assertEqual(len(lines), 1)

    def test_cron_scan(self):
        session = self._open_session()
        self._cash_move(session, 'out', 5.0, 'tips')
        session.cash_move_ids.unlink()
        self.env['pos.cash.move']._cron_sync_pos_cash()
        self.assertEqual(len(session.cash_move_ids), 1)

    # ------------------------------------------------------------------
    # Partner payments
    # ------------------------------------------------------------------

    def _vendor_bill(self, amount):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'invoice_date': '2026-01-01',
            'invoice_line_ids': [(0, 0, {
                'name': 'Meat', 'quantity': 1, 'price_unit': amount,
                'account_id': self.expense_account.id, 'tax_ids': [(6, 0, [])],
            })],
        })
        bill.action_post()
        return bill

    def test_cash_out_paid_to_vendor_reconciled_with_bill(self):
        bill = self._vendor_bill(30.0)
        session = self._open_session()
        move = self._cash_move(session, 'out', 30.0, 'paid meat supplier')
        move.write({'classification_type': 'partner', 'partner_id': self.vendor.id, 'bill_id': bill.id})
        self.assertEqual(move.partner_account_id, self.vendor.property_account_payable_id)
        move.action_classify()
        self.assertEqual(move.state, 'classified')
        _liq, suspense, other = move.statement_line_id._seek_for_lines()
        self.assertFalse(suspense)
        self.assertEqual(other.account_id, self.vendor.property_account_payable_id)
        self.assertEqual(other.partner_id, self.vendor)
        self.assertEqual(bill.payment_state, 'paid')

        # Reset unreconciles the bill
        move.action_reset()
        self.assertEqual(bill.payment_state, 'not_paid')
        self.assertFalse(move.statement_line_id.partner_id)

    def test_cash_out_to_vendor_shows_as_outstanding(self):
        bill = self._vendor_bill(50.0)
        session = self._open_session()
        move = self._cash_move(session, 'out', 20.0, 'advance to supplier')
        move.write({'classification_type': 'partner', 'partner_id': self.vendor.id})
        move.action_classify()
        self.assertEqual(bill.payment_state, 'not_paid')
        bill.invalidate_recordset(['invoice_has_outstanding'])
        self.assertTrue(bill.invoice_has_outstanding, 'The cash payment must be offered on the bill')

    def test_partner_required(self):
        session = self._open_session()
        move = self._cash_move(session, 'out', 5.0, 'x')
        move.classification_type = 'partner'
        with self.assertRaises(UserError):
            move.action_classify()

    def test_cash_difference_to_vendor(self):
        bill = self._vendor_bill(5.0)
        session = self._open_session()
        self._cash_move(session, 'out', 20.0, 'gas')
        self._close(session, -25.0)  # 5 missing: cashier paid the vendor without recording it
        diff = session.cash_difference_ids
        diff.write({'classification_type': 'partner', 'partner_id': self.vendor.id, 'bill_id': bill.id})
        diff.action_classify()
        payable_line = diff.correcting_move_id.line_ids.filtered(
            lambda l: l.account_id == self.vendor.property_account_payable_id)
        self.assertEqual(payable_line.debit, 5.0)
        self.assertEqual(payable_line.partner_id, self.vendor)
        self.assertEqual(bill.payment_state, 'paid')
        diff.action_reset()
        self.assertEqual(bill.payment_state, 'not_paid')
        self.assertEqual(diff.state, 'pending')
