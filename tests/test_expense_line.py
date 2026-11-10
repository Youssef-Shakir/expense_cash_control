# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import ExpenseCashCommon


@tagged('post_install', '-at_install')
class TestExpenseLine(ExpenseCashCommon):
    """Expenses and POS cash-outs classified to a category in one list, without booking anything twice."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cash_method = cls.env['pos.payment.method'].create({'name': 'ECC Cash', 'journal_id': cls.cash_journal.id})
        cls.config = cls.env['pos.config'].create({
            'name': 'ECC Lines POS', 'payment_method_ids': [(6, 0, cls.cash_method.ids)]})

    def test_expenses_and_classified_cash_outs(self):
        session = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        session.set_opening_control(0, '')
        for amount, reason in ((25.0, 'ice'), (40.0, 'vendor'), (10.0, 'not yet')):
            session.try_cash_in_out('out', amount, reason, {'translatedType': 'out', 'formattedAmount': str(amount)})
        ice, vendor, pending = session.cash_move_ids.sorted('id')
        ice.category_id = self.category
        ice.action_classify()
        vendor.write({'classification_type': 'partner', 'partner_id': self.vendor.id})
        vendor.action_classify()
        expense = self.env['expense.express'].create({
            'name': 'Tomatoes', 'amount': 40.0, 'category_id': self.category.id, 'journal_id': self.cash_journal.id})
        self.env.flush_all()

        Line = self.env['ecc.expense.line']
        lines = Line.search(['|', ('cash_move_id', 'in', (ice | vendor | pending).ids), ('expense_id', '=', expense.id)])
        self.assertEqual(len(lines), 2, 'the vendor payment and the unclassified cash-out are not expenses')
        pos = lines.filtered(lambda l: l.source == 'pos')
        self.assertEqual((pos.cash_move_id, pos.amount, pos.category_id, pos.config_id, pos.payment_mode),
                         (ice, 25.0, self.category, self.config, 'paid'))
        self.assertEqual(lines.filtered(lambda l: l.source == 'expense').expense_id, expense)
        self.assertEqual(pos.action_open_source()['res_model'], 'pos.cash.move')

        # shown, not booked twice: the category account holds the cash-out once
        booked = sum(self.env['account.move.line'].search([
            ('account_id', '=', self.expense_account.id), ('parent_state', '=', 'posted')]).mapped('debit'))
        self.assertAlmostEqual(booked, 65.0)
