# -*- coding: utf-8 -*-
{
    'name': 'Expenses & Cash Control',
    'version': '18.0.2.0.0',
    'category': 'Accounting/Expenses',
    'summary': 'Record expenses and bills, categorize POS cash in/out, reconcile cash differences and review closed sessions',
    'description': """
Expenses & Cash Control | المصروفات ومراقبة النقد
================================================

One app for the daily money flow of a restaurant or shop:

* Quick expenses paid now (cash / bank) with automatic journal entries
* Expenses to pay later, recorded as real vendor bills that wait for payment
* Receipts and documents attached to every expense
* Categorized Cash In / Cash Out directly from the POS
* Daily reconciliation of uncategorized POS cash in/out
* Classification of POS cash differences (loss / gain)
* Cash review of every closed POS session

Merges and replaces the former "Expenses Press" (expense_express) and
"POS Cash In/Out Categories" (pos_cash_category) modules.

Developed by Yousif Shakir - Donialink | تطوير يوسف شاكر
    """,
    'author': 'Donialink, Yousif Shakir',
    'maintainer': 'Yousif Shakir',
    'website': 'https://www.donialink.com',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'point_of_sale',
        'mail',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/expense_category_views.xml',
        'views/expense_views.xml',
        'views/pos_cash_move_views.xml',
        'views/cash_difference_views.xml',
        'views/pos_session_views.xml',
        'views/pos_config_views.xml',
        'views/dashboard_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'expense_cash_control/static/src/scss/expense_cash_control.scss',
            'expense_cash_control/static/src/dashboard/*',
        ],
        'point_of_sale._assets_pos': [
            'expense_cash_control/static/src/pos/*',
        ],
    },
    'pre_init_hook': 'pre_init_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
    'sequence': 10,
}
