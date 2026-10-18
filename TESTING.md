# Manual test checklist (on a clone of the live database)

Work on a **copy** of live. Tick each box; note anything odd next to it.

## 0. Before migrating — take notes
- [ ] Count expenses: *Expenses Press › All Expenses* → total count and **sum of amounts**: ________
- [ ] Count cash differences and how many are *Classified*: ________
- [ ] Open 2 old expenses and write down their journal entry numbers: ________
- [ ] Note the next CDR number (last cash difference reference): ________
- [ ] Is `pos_cash_category` installed? (Apps, remove "Apps" filter) ________

## 1. Migration
- [ ] `pg_dump` backup done.
- [ ] Run `scripts/migrate_from_expense_express.sql` → message "Renamed expense_express to expense_cash_control".
- [ ] `odoo -u expense_cash_control --i18n-overwrite --stop-after-init` finishes without ERROR.
- [ ] Odoo starts; the app is called **المصروفات والنقد / Expenses & Cash** with the new icon.
- [ ] Same expense count and sum as step 0. The 2 noted expenses still point to the **same** entry numbers.
- [ ] Same cash differences, classified ones still show their correcting entry.
- [ ] A new cash difference continues the CDR numbering (no duplicate CDR/0001).
- [ ] A normal (non-admin) user still sees and can create expenses.

## 2. Expenses
- [ ] *Overview › New Expense*, Paid Now, 50, category, attach a photo → saved, posted, entry in the cash journal, photo visible on the entry.
- [ ] Edit an **old** expense amount (not the last one) → saves without "sequence" error, entry number unchanged.
- [ ] *New Bill to Pay*: without vendor → refused; with vendor → vendor bill posted, total = amount (no tax), "Not Paid".
- [ ] Set a due date in the past → red *Overdue* ribbon, appears in *Bills to Pay* and the Overview counter.
- [ ] *Register Payment* (cash) → Paid ribbon; the expense fields become read-only.
- [ ] Partial payment on another bill → *Partially Paid*, *Amount Due* correct.
- [ ] Delete an unpaid expense → its entry/bill is deleted (or cancelled if not last in sequence).
- [ ] Filters: Waiting for Payment, Overdue, Missing Receipt, Today; Expense Analysis (graph/pivot).

## 3. POS with categories (Settings › POS › Accounting › Cash In/Out Categories)
- [ ] Mark 2–3 categories *Available in POS* (one with direction *Cash In*).
- [ ] In the POS: Cash Out → only Cash Out categories shown; pick one, no note → Confirm enabled, receipt prints with the category name.
- [ ] Cash In → only Cash In / Both categories.
- [ ] Without category: needs a reason (or is blocked if *Category Required* is on).
- [ ] Back office *POS Cash › Cash In / Out*: categorized moves are *Classified / At POS*, journal entry on the category account.

## 4. POS without categories (daily reconciliation)
- [ ] Disable the option on a POS, make 2 cash outs and 1 cash in with reasons.
- [ ] *POS Cash › Cash In / Out* (or *Scan Now*) → 3 lines *To Classify*, grouped by day, cashier shown.
- [ ] Pick categories inline → *Classify*; select several → *Classify Selected*.
- [ ] *Reset to Classify* on one → back on suspense, can be classified again.

## 5. Closing & session review
- [ ] Close a session with a wrong count (e.g. 5 short).
- [ ] *POS Cash › Session Reviews* → the session is *To Review*; cards show opening, in, out, expected, counted, difference.
- [ ] *Mark as Reviewed* is refused while items are unclassified.
- [ ] Classify the cash in/out and the difference from the tabs → green banner → *Mark as Reviewed* → Reviewed, reviewer and date set, logged in the chatter.
- [ ] *Reopen Review* works. The standard POS session form shows the *Cash Review* button.
- [ ] Close a session as an **Arabic** user with a difference → it is still detected.

## 5b. Cash paid to a vendor (partner payment)
- [ ] Create a vendor bill of 40 for vendor X and post it.
- [ ] In the POS make a Cash Out of 40 "paid X" (no category).
- [ ] In *Cash In / Out* (or the session review): *Goes To* = Partner Payment, Partner = X, Bill = that bill → *Classify* → the bill is **Paid**.
- [ ] Another cash out of 15 to X **without** a bill → open any open bill of X → "Outstanding debits" lists it → *Add* → bill partially paid.
- [ ] Pay more than the bill (e.g. 12 on a bill of 7) → bill paid, 5 stays outstanding for the next bill.
- [ ] A cash difference (shortage) classified to vendor X → correcting entry debits X's payable account → appears as outstanding on X's bills.
- [ ] Only vendor bills / customer refunds are offered for cash out; only customer invoices / vendor refunds for cash in.
- [ ] *Reset* on a partner payment linked to a bill → the bill goes back to Not Paid.
- [ ] Vendor ledger (Accounting › Partner Ledger) for X shows the cash payments.

## 6. Reports & accounting check
- [ ] Profit & Loss for the test period: expense accounts include expenses, classified cash outs and differences.
- [ ] Cash journal suspense account: no balance left from classified moves.
- [ ] Cash difference correcting entries are in the **Miscellaneous** journal.

## 7. Rights
- [ ] A user without Manager rights: no *POS Cash* / *Configuration* menus, can still record expenses.
- [ ] A POS cashier (POS user only) can still do Cash In/Out and close sessions.
