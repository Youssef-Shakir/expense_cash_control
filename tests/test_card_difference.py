# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ExpenseCashCommon


@tagged('post_install', '-at_install')
class TestCardDifference(ExpenseCashCommon):
    """Card / bank closing differences show in the session review next to the cash difference."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['account.account']
        cls.loss_account = Account.create({'name': 'ECC Diff Loss', 'code': 'ECC6998', 'account_type': 'expense'})
        cls.gain_account = Account.create({'name': 'ECC Diff Gain', 'code': 'ECC7998', 'account_type': 'income_other'})
        cls.cash_journal.write({'loss_account_id': cls.loss_account.id, 'profit_account_id': cls.gain_account.id})
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'ECC Test Card', 'code': 'ECCB', 'type': 'bank',
            'loss_account_id': cls.loss_account.id, 'profit_account_id': cls.gain_account.id,
        })
        cls.cash_method = cls.env['pos.payment.method'].create({
            'name': 'ECC Cash', 'journal_id': cls.cash_journal.id,
        })
        cls.card_method = cls.env['pos.payment.method'].create({
            'name': 'ECC Card', 'journal_id': cls.bank_journal.id,
        })
        cls.config = cls.env['pos.config'].create({
            'name': 'ECC Card POS',
            'payment_method_ids': [(6, 0, (cls.cash_method | cls.card_method).ids)],
        })
        cls.product = cls.env['product.product'].create({
            'name': 'ECC Burger', 'available_in_pos': True, 'list_price': 100.0, 'taxes_id': [(6, 0, [])],
        })

    def _open_session(self):
        session = self.env['pos.session'].create({'config_id': self.config.id, 'user_id': self.env.uid})
        session.set_opening_control(0, '')
        return session

    def _order(self, session, method, amount):
        order = self.env['pos.order'].create({
            'session_id': session.id,
            'partner_id': self.vendor.id,
            'lines': [(0, 0, {
                'product_id': self.product.id, 'qty': 1, 'price_unit': amount,
                'price_subtotal': amount, 'price_subtotal_incl': amount,
            })],
            'amount_total': amount, 'amount_tax': 0.0, 'amount_paid': 0.0, 'amount_return': 0.0,
        })
        self.env['pos.make.payment'].with_context(active_id=order.id, active_ids=order.ids).create({
            'payment_method_id': method.id, 'amount': amount,
        }).check()
        return order

    def _close(self, session, counted_cash, card_diffs):
        session.post_closing_cash_details(counted_cash)
        session.close_session_from_ui(list(card_diffs.items()))
        self.assertEqual(session.state, 'closed')

    def test_cash_order_registered_as_card(self):
        """Cash order rung up as card: +100 in the drawer, -100 on the terminal, net 0."""
        session = self._open_session()
        self._order(session, self.card_method, 100.0)
        self._close(session, 100.0, {self.card_method.id: -100.0})

        diffs = session.cash_difference_ids
        self.assertEqual(len(diffs), 2)
        cash = diffs.filtered(lambda d: d.source == 'cash')
        card = diffs.filtered(lambda d: d.source == 'card')
        self.assertEqual((cash.difference_type, cash.amount), ('gain', 100.0))
        self.assertEqual((card.difference_type, card.amount), ('loss', 100.0))
        self.assertEqual(card.payment_method_id, self.card_method)
        self.assertEqual(cash.payment_method_id, self.cash_method)

        self.assertAlmostEqual(session.card_expected_total, 100.0)
        self.assertAlmostEqual(session.card_counted_total, 0.0)
        self.assertAlmostEqual(session.card_difference, -100.0)
        self.assertAlmostEqual(session.total_difference, 0.0)
        self.assertTrue(session.differences_offset)

        # Both must be classified before the review is done; same category -> they cancel out.
        self.assertEqual(session.cash_difference_pending_count, 2)
        diffs.category_id = self.category
        diffs.action_classify()
        session.action_cash_review_done()
        self.assertEqual(session.cash_review_state, 'reviewed')
        category_balance = sum(diffs.correcting_move_id.line_ids.filtered(
            lambda l: l.account_id == self.expense_account).mapped('balance'))
        self.assertAlmostEqual(category_balance, 0.0)

        # Refreshing does not create them twice.
        session.action_cash_review_refresh()
        self.assertEqual(len(session.cash_difference_ids), 2)

    def test_split_card_method_difference(self):
        # Odoo only posts a split method's closing difference when it has an outstanding account.
        self.card_method.write({
            'split_transactions': True,
            'outstanding_account_id': self.env['account.account'].create({
                'name': 'ECC Card Outstanding', 'code': 'ECC1099', 'account_type': 'asset_current',
                'reconcile': True}).id,
        })
        session = self._open_session()
        self._order(session, self.card_method, 40.0)
        self._close(session, 0.0, {self.card_method.id: 5.0})
        card = session.cash_difference_ids.filtered(lambda d: d.source == 'card')
        self.assertEqual((card.difference_type, card.amount), ('gain', 5.0))
        self.assertEqual(card.session_id, session)
        self.assertEqual(card.payment_method_id, self.card_method)
        self.assertAlmostEqual(session.card_counted_total, 45.0)
        self.assertFalse(session.differences_offset)

    def test_cron_finds_card_difference(self):
        session = self._open_session()
        self._order(session, self.card_method, 30.0)
        self._close(session, 0.0, {self.card_method.id: -10.0})
        session.cash_difference_ids.unlink()
        self.env['pos.cash.move']._cron_sync_pos_cash()
        card = session.cash_difference_ids.filtered(lambda d: d.source == 'card')
        self.assertEqual((card.difference_type, card.amount), ('loss', 10.0))

    def test_admin_report_card_counted(self):
        """The admin closing report shows the card counted amount, also when reprinted after closing."""
        if 'pos_admin_session_report' not in self.env.registry._init_modules:
            self.skipTest('pos_admin_session_report not installed')
        session = self._open_session()
        self._order(session, self.card_method, 100.0)
        self._close(session, 100.0, {self.card_method.id: -100.0})
        closing = self.env['pos.session']._report_closing(session)
        card = next(m for m in closing['methods'] if m['method'] == 'ECC Card')
        self.assertAlmostEqual(card['expected'], 100.0)
        self.assertAlmostEqual(card['counted'], 0.0)
        self.assertAlmostEqual(card['difference'], -100.0)
        self.assertAlmostEqual(closing['total_difference'], 0.0)

    def test_forgotten_card_difference(self):
        """Paid by card but rung up as cash, and the card total not entered at closing: the drawer is short and
        no card difference was posted. The review records the card difference afterwards; they cancel out."""
        session = self._open_session()
        self._order(session, self.cash_method, 100.0)
        self._close(session, 0.0, {})
        self.assertEqual(len(session.cash_difference_ids), 1)
        self.assertAlmostEqual(session.card_difference, 0.0)

        wizard = self.env['ecc.session.card.difference'].with_context(default_session_id=session.id).create({
            'amount': 100.0, 'difference_type': 'gain', 'name': 'Order paid by card, entered as cash'})
        self.assertEqual(wizard.payment_method_id, self.card_method)
        self.assertAlmostEqual(wizard.total_after, 0.0)
        wizard.action_confirm()

        card = session.cash_difference_ids.filtered(lambda d: d.source == 'card')
        self.assertEqual((card.difference_type, card.amount, card.payment_method_id), ('gain', 100.0, self.card_method))
        self.assertEqual(card.original_move_id.state, 'posted')
        session.invalidate_recordset()
        self.assertAlmostEqual(session.card_difference, 100.0)
        self.assertAlmostEqual(session.total_difference, 0.0)
        self.assertTrue(session.differences_offset)

        # found again by a refresh / the cron? never twice
        session.action_cash_review_refresh()
        self.assertEqual(len(session.cash_difference_ids.filtered(lambda d: d.source == 'card')), 1)

        session.cash_difference_ids.category_id = self.category
        session.cash_difference_ids.action_classify()
        session.action_cash_review_done()
        with self.assertRaises(UserError):
            session._ecc_add_card_difference(self.card_method, 5.0, 'gain')
