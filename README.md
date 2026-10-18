# Expenses & Cash Control | المصروفات ومراقبة النقد

Odoo 18 Community · Developed by **Yousif Shakir** · [donialink.com](https://www.donialink.com)

Replaces and merges **Expenses Press** (`expense_express`) and **POS Cash In/Out Categories** (`pos_cash_category`).

## Features

| Area | What it does |
|---|---|
| Expenses – Paid Now | Posted journal entry: expense account ← cash / bank journal account. |
| Expenses – To Pay Later | Real **vendor bill** (vendor required, no tax added) that waits for payment: *Register Payment*, Paid / Partially Paid / Overdue ribbons, "Bills to Pay" menu. A bill with a payment locks the expense. |
| Receipts | Upload photos / PDFs on the expense; they are linked to the expense and copied on the journal entry / bill. |
| Editing | The accounting document is rewritten **in place** (same number). Fixes the old "sequence chain" error when editing an old expense. |
| POS Cash In/Out categories | Optional per POS (Settings › Point of Sale › Accounting). The standard popup gets a category picker; the move is posted directly on the category account. Option "Category Required". |
| Daily cash in/out reconciliation | Uncategorized cash in/out (sitting on the cash journal suspense account) appear in *POS Cash › Cash In / Out*, grouped by day. Pick a category → **Classify** (or *Classify Selected*). *Reset* puts it back on suspense. Collected on session close, by an hourly cron and with *Scan Now*. |
| Cash differences | Detected on session close (no longer depends on the language of the label). Reclassified to a category with a correcting entry in the Miscellaneous journal. *Reset* cancels it. |
| Partner payments | On any cash in/out or cash difference, *Goes To* = **Partner Payment**: pick the vendor (or customer). The amount is posted on the partner's payable account (money out) or receivable account (money in), with the partner set. Choose a *Bill / Invoice* to reconcile at once, or leave it empty: it then appears on the partner's open bills as an **outstanding debit** to *Add* later. Overpayments stay as an advance. *Reset* unreconciles. |
| Session review | Every closed session with a cash drawer becomes *To Review*: opening, cash in, cash out, expected, counted, difference, inline classification. *Mark as Reviewed* is refused while something is unclassified. |
| Overview | Dashboard: spent today / this month (trend), bills to pay, POS items to classify, sessions to review, top categories, recent expenses. |
| Security | *User* (all internal users, as before) records expenses; *Manager* (admins + accounting managers) classifies, reviews, configures. Multi-company rules. |
| Arabic | Full `ar.po`, RTL-friendly styles. |

## Migrating a database that uses Expenses Press

The models keep their names, so the module is **renamed in the database** — no data is copied.

```bash
# 1. backup
pg_dump -Fc -d LIVE > live_before_ecc.dump
# 2. stop Odoo, put expense_cash_control in the addons path, remove expense_express from it
# 3. rename
psql -d LIVE -f expense_cash_control/scripts/migrate_from_expense_express.sql
# 4. upgrade (loads the new views, groups and Arabic translations)
odoo -d LIVE -u expense_cash_control --i18n-overwrite --stop-after-init
# 5. start Odoo
```

Do **not** install `expense_cash_control` next to `expense_express`: the install is refused on purpose.
If `pos_cash_category` was installed, uninstall it first (its categories are not migrated: recreate them as
expense categories with *Available in POS*).

## Tests

```bash
odoo -d DB -u expense_cash_control --test-enable --test-tags /expense_cash_control --stop-after-init
```

See `TESTING.md` for the manual checklist.
