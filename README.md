# Brightloop Subscription Management System

One system to run products, plans, subscriptions, invoices, payments and revenue reports for a subscription business.
Stack: Python, Flask, SQLite (local database, works fully offline), plain HTML and CSS.

## Run it (Windows)
```
py -m pip install -r requirements.txt
py seed.py        # optional: fills realistic demo data (customers, products, plans, subscriptions, invoices, payments)
py app.py
```
Open http://127.0.0.1:5000

| Role | Login |
|---|---|
| Admin | admin@brightloop.com / Admin@12345! |
| Customer | sign up on the Sign up page (or use a seeded customer after resetting their password) |

## What it does
- **Accounts:** sign up with one account per email and a strong password (more than 8 characters, upper, lower, special). Password reset link (printed in the console for the demo).
- **Roles:** admin (everything, adds staff), staff (day-to-day, limited), customer (portal: only their own subscriptions and invoices).
- **Catalog (admin):** taxes, products with variants (for example Brand: Odoo adds 560), plans (daily, weekly, monthly, yearly, minimum quantity, dates, auto-close and closable rules), discounts (fixed or percent, minimum purchase or quantity, dates, usage limit, per product or whole subscription).
- **Subscriptions:** numbered, with lines, taxes and totals. Status flow: Draft, Quotation, Confirmed, Active, Closed. Quotation templates with a validity period.
- **Billing day:** one "Run Billing" button creates invoices from active subscriptions with taxes and discounts applied. Nothing is billed twice: checked in code and enforced by a database unique constraint.
- **Invoices:** Draft, Confirmed, Paid. Confirm, cancel, send and print.
- **Payments:** recorded by method, amount, date and note against an invoice. The invoice becomes Paid when payments cover the total. Overdue invoices are listed to chase.
- **Finance dashboard:** monthly recurring revenue, active subscriptions, revenue collected, outstanding, overdue invoices, revenue chart and revenue at risk (overdue plus subscriptions expiring within 7 days). Tested with 3,000 subscriptions and 9,000 invoices: every page loads in under 2 seconds.

## Known limitations (honest list)
- Emails (password reset, invoice send) are printed in the console instead of sent through an email server.
- The plan options "pausable" and "renewable" are stored but pause and renew actions are not built yet. Closing early and auto-close work.
- Long lists are not paginated yet.

## Team and Git
Two members, both committing their own work to `main`. See the commit history for who built what.
