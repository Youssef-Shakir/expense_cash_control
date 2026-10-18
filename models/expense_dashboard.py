# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class ExpenseCashDashboard(models.AbstractModel):
    _name = 'expense.cash.dashboard'
    _description = 'Expenses & Cash Control Dashboard'

    @api.model
    def get_dashboard_data(self):
        company = self.env.company
        currency = company.currency_id
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        last_month_start = month_start - relativedelta(months=1)

        Expense = self.env['expense.express']
        company_domain = [('company_id', '=', company.id)]

        def total(model, domain, field='amount'):
            data = model._read_group(domain, [], ['__count', '%s:sum' % field])
            count, amount = data[0] if data else (0, 0.0)
            return {'count': count, 'amount': amount or 0.0, 'amount_fmt': currency.format(amount or 0.0)}

        today_stats = total(Expense, company_domain + [('date', '=', today)])
        month_stats = total(Expense, company_domain + [('date', '>=', month_start)])
        last_month_stats = total(Expense, company_domain + [('date', '>=', last_month_start), ('date', '<', month_start)])
        unpaid_stats = total(Expense, company_domain + [
            ('payment_mode', '=', 'to_pay'), ('payment_state', 'in', ('not_paid', 'partial')),
        ], field='amount_residual')
        overdue_count = Expense.search_count(company_domain + [('is_overdue', '=', True)])

        CashMove = self.env['pos.cash.move']
        cash_domain = company_domain + [('state', '=', 'to_classify')]
        cash_out = total(CashMove, cash_domain + [('move_type', '=', 'out')], field='amount_abs')
        cash_in = total(CashMove, cash_domain + [('move_type', '=', 'in')], field='amount_abs')

        Difference = self.env['cash.difference.reconciliation']
        diff_domain = company_domain + [('state', '=', 'pending')]
        losses = total(Difference, diff_domain + [('difference_type', '=', 'loss')])
        gains = total(Difference, diff_domain + [('difference_type', '=', 'gain')])

        sessions_to_review = self.env['pos.session'].search_count(
            company_domain + [('cash_review_state', '=', 'to_review')])
        open_sessions = self.env['pos.session'].search_count(
            company_domain + [('state', 'in', ('opened', 'closing_control'))])

        by_category = Expense._read_group(
            company_domain + [('date', '>=', month_start)], ['category_id'], ['amount:sum'],
            order='amount:sum desc', limit=6)
        month_total = month_stats['amount'] or 1.0
        top_categories = [{
            'id': category.id,
            'name': category.display_name,
            'color': category.color,
            'amount_fmt': currency.format(amount),
            'percent': round(amount * 100.0 / month_total),
        } for category, amount in by_category]

        recent = Expense.search(company_domain, limit=6)
        recent_expenses = [{
            'id': expense.id,
            'name': expense.name,
            'date': fields.Date.to_string(expense.date),
            'category': expense.category_id.display_name,
            'amount_fmt': currency.format(expense.amount),
            'payment_mode': expense.payment_mode,
            'payment_state': expense.payment_state,
            'has_attachment': bool(expense.attachment_ids),
        } for expense in recent]

        trend = None
        if last_month_stats['amount']:
            trend = round((month_stats['amount'] - last_month_stats['amount']) * 100.0 / last_month_stats['amount'])

        return {
            'currency': {'symbol': currency.symbol, 'position': currency.position},
            'company': company.name,
            'today': today_stats,
            'month': month_stats,
            'last_month': last_month_stats,
            'month_trend': trend,
            'unpaid': unpaid_stats,
            'overdue_count': overdue_count,
            'cash_out': cash_out,
            'cash_in': cash_in,
            'to_classify_count': cash_out['count'] + cash_in['count'],
            'losses': losses,
            'gains': gains,
            'differences_count': losses['count'] + gains['count'],
            'sessions_to_review': sessions_to_review,
            'open_sessions': open_sessions,
            'top_categories': top_categories,
            'recent_expenses': recent_expenses,
            'is_manager': self.env.user.has_group('expense_cash_control.group_expense_manager'),
        }
