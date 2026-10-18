# -*- coding: utf-8 -*-
import base64

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ExpenseCashCommon


@tagged('post_install', '-at_install')
class TestExpense(ExpenseCashCommon):

    def _expense(self, **vals):
        return self.env['expense.express'].create({
            'name': 'Tomatoes', 'amount': 40.0, 'category_id': self.category.id,
            'journal_id': self.cash_journal.id, **vals,
        })

    def test_paid_now_creates_posted_entry(self):
        expense = self._expense()
        self.assertEqual(expense.state, 'posted')
        self.assertEqual(expense.payment_state, 'paid')
        move = expense.move_id
        self.assertEqual(move.move_type, 'entry')
        self.assertEqual(move.state, 'posted')
        debit = move.line_ids.filtered(lambda l: l.debit)
        credit = move.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(debit.account_id, self.expense_account)
        self.assertEqual(credit.account_id, self.cash_journal.default_account_id)
        self.assertEqual(debit.debit, 40.0)

    def test_edit_rewrites_entry_in_place(self):
        """Editing an older expense must keep its entry number (no sequence gap)."""
        first = self._expense()
        self._expense(name='Onions')  # first is no longer the last of the sequence
        move, number = first.move_id, first.move_id.name
        first.write({'amount': 55.0})
        self.assertEqual(first.move_id, move)
        self.assertEqual(first.move_id.name, number)
        self.assertEqual(first.move_id.state, 'posted')
        self.assertEqual(first.move_id.amount_total, 55.0)

    def test_to_pay_later_creates_vendor_bill(self):
        expense = self._expense(payment_mode='to_pay', partner_id=self.vendor.id,
                                journal_id=self.purchase_journal.id)
        bill = expense.move_id
        self.assertEqual(bill.move_type, 'in_invoice')
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.partner_id, self.vendor)
        self.assertEqual(bill.amount_total, 40.0, 'No tax must be added on top of the typed amount')
        self.assertEqual(expense.payment_state, 'not_paid')
        self.assertEqual(expense.amount_residual, 40.0)

        # Pay it through the standard payment wizard
        action = expense.action_register_payment()
        wizard = self.env[action['res_model']].with_context(action['context']).create({
            'journal_id': self.cash_journal.id,
        })
        wizard.action_create_payments()
        self.assertIn(expense.payment_state, ('paid', 'in_payment'))

        # A paid bill can't be changed from the expense
        with self.assertRaises(UserError):
            expense.amount = 50.0

    def test_to_pay_later_requires_vendor(self):
        with self.assertRaises(UserError):
            self._expense(payment_mode='to_pay', journal_id=self.purchase_journal.id)

    def test_switch_mode_replaces_document(self):
        expense = self._expense(payment_mode='to_pay', partner_id=self.vendor.id,
                                journal_id=self.purchase_journal.id)
        bill = expense.move_id
        expense.write({'payment_mode': 'paid', 'journal_id': self.cash_journal.id})
        self.assertEqual(expense.move_id.move_type, 'entry')
        self.assertFalse(bill.exists() and bill.state == 'posted', 'The old bill is removed or cancelled')

    def test_attachments_are_linked_and_copied(self):
        attachment = self.env['ir.attachment'].create({
            'name': 'receipt.txt', 'datas': base64.b64encode(b'receipt'), 'res_model': 'expense.express', 'res_id': 0,
        })
        expense = self._expense(attachment_ids=[(6, 0, attachment.ids)])
        self.assertEqual(attachment.res_id, expense.id)
        self.assertEqual(expense.attachment_count, 1)
        on_move = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'), ('res_id', '=', expense.move_id.id)])
        self.assertEqual(len(on_move), 1)
        # Editing does not duplicate it
        expense.amount = 41.0
        self.assertEqual(self.env['ir.attachment'].search_count([
            ('res_model', '=', 'account.move'), ('res_id', '=', expense.move_id.id)]), 1)

    def test_delete_removes_entry(self):
        expense = self._expense()
        move = expense.move_id
        expense.unlink()
        self.assertFalse(move.exists() and move.state == 'posted')

    def test_amount_must_be_positive(self):
        with self.assertRaises(UserError):
            self._expense(amount=0.0)

    def test_dashboard_data(self):
        self._expense()
        data = self.env['expense.cash.dashboard'].get_dashboard_data()
        self.assertGreaterEqual(data['today']['count'], 1)
        self.assertIn('recent_expenses', data)
