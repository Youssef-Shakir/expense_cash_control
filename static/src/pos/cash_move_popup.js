/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CashMovePopup } from "@point_of_sale/app/navbar/cash_move_popup/cash_move_popup";

// Adds a category picker to the standard Cash In / Cash Out popup. The
// category is sent to the server with the move, which posts it directly on
// the category account (see pos.session._prepare_account_bank_statement_line_vals).
patch(CashMovePopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.cashCategoryId = false;
    },

    get useCashCategories() {
        return Boolean(this.pos.config.use_cash_categories) && this.allCashCategories.length > 0;
    },

    get cashCategoryRequired() {
        return this.useCashCategories && Boolean(this.pos.config.cash_category_required);
    },

    get allCashCategories() {
        return this.pos.models["expense.category"]?.getAll() || [];
    },

    get cashCategories() {
        const type = this.state.type;
        return this.allCashCategories
            .filter((category) => category.pos_cash_type === "both" || category.pos_cash_type === type)
            .sort((a, b) => a.sequence - b.sequence || a.name.localeCompare(b.name));
    },

    get selectedCashCategory() {
        return this.allCashCategories.find((category) => category.id === this.state.cashCategoryId);
    },

    selectCashCategory(category) {
        this.state.cashCategoryId = this.state.cashCategoryId === category.id ? false : category.id;
    },

    onClickButton(type) {
        super.onClickButton(type);
        if (!this.cashCategories.some((category) => category.id === this.state.cashCategoryId)) {
            this.state.cashCategoryId = false;
        }
    },

    isValidCashMove() {
        if (!this.useCashCategories) {
            return super.isValidCashMove();
        }
        const validAmount = this.env.utils.isValidFloat(this.state.amount);
        if (this.state.cashCategoryId) {
            // The category is a good enough reason.
            return validAmount;
        }
        return !this.cashCategoryRequired && super.isValidCashMove();
    },

    async confirm() {
        const category = this.selectedCashCategory;
        if (category) {
            const note = this.state.reason.trim();
            this.state.reason = note ? `${category.name}: ${note}` : category.name;
        }
        return super.confirm(...arguments);
    },

    _prepare_try_cash_in_out_payload(type, amount, reason, extras) {
        const payload = super._prepare_try_cash_in_out_payload(...arguments);
        if (this.state.cashCategoryId) {
            payload[4] = { ...payload[4], expense_category_id: this.state.cashCategoryId };
        }
        return payload;
    },
});
