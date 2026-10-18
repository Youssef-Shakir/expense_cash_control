# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class ExpenseCashCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Account = cls.env['account.account']
        cls.expense_account = Account.create({
            'name': 'ECC Test Expense', 'code': 'ECC6001', 'account_type': 'expense',
        })
        cls.income_account = Account.create({
            'name': 'ECC Test Other Income', 'code': 'ECC7001', 'account_type': 'income_other',
        })
        cls.category = cls.env['expense.category'].create({
            'name': 'ECC Vegetables', 'code': 'ECC-VEG', 'account_id': cls.expense_account.id,
            'available_in_pos': True, 'pos_cash_type': 'out',
        })
        cls.category_in = cls.env['expense.category'].create({
            'name': 'ECC Owner Deposit', 'code': 'ECC-DEP', 'account_id': cls.income_account.id,
            'available_in_pos': True, 'pos_cash_type': 'in',
        })
        cls.cash_journal = cls.env['account.journal'].create({
            'name': 'ECC Test Cash', 'code': 'ECCC', 'type': 'cash',
        })
        cls.purchase_journal = cls.env['account.journal'].search([
            ('type', '=', 'purchase'), ('company_id', '=', cls.company.id)], limit=1)
        cls.vendor = cls.env['res.partner'].create({'name': 'ECC Market Vendor'})
