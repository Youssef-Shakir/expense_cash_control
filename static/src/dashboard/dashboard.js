/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class ExpenseCashDashboard extends Component {
    static template = "expense_cash_control.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, loading: true });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("expense.cash.dashboard", "get_dashboard_data", []);
        this.state.loading = false;
    }

    get trendClass() {
        const trend = this.state.data.month_trend;
        if (trend === null || trend === undefined) {
            return "";
        }
        return trend > 0 ? "o_ecc_trend_up" : "o_ecc_trend_down";
    }

    open(xmlId, context = {}) {
        return this.action.doAction(xmlId, { additionalContext: context });
    }

    newExpense(paymentMode = "paid") {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: paymentMode === "to_pay" ? _t("New Bill to Pay") : _t("New Expense"),
            res_model: "expense.express",
            views: [[false, "form"]],
            target: "current",
            context: { default_payment_mode: paymentMode },
        });
    }

    openExpenses(context) {
        return this.open("expense_cash_control.action_expense_express", context);
    }

    openExpense(id) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "expense.express",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openCategory(id) {
        return this.openExpenses({ search_default_filter_this_month: 1, search_default_category_id: id });
    }

    async scanPos() {
        await this.orm.call("pos.cash.move", "action_scan", []);
        await this.orm.call("cash.difference.reconciliation", "action_detect_cash_differences", []);
        await this.load();
    }
}

registry.category("actions").add("expense_cash_control.dashboard", ExpenseCashDashboard);
