# Brightloop Subscription Management System

Hackathon project: products, plans, subscriptions, invoices, payments and a finance dashboard.
Stack: Python, Flask, SQLite (local, works offline), plain HTML/CSS.

## Run it
```
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000
Admin login: admin@brightloop.com / Admin@12345!

## Git rules for the team
- Both of us commit our OWN work, with clear messages ("added tax list page").
- `git pull` before starting and before pushing. Push at least every hour.
- Do not edit the same file at the same time (see split below).

## Who builds what
| Area | Owner | Files |
|---|---|---|
| Auth, roles, DB models, subscription flow, invoice generation, discounts, dashboard | Ardhra | app.py, models.py, templates/subscriptions*, invoices*, dashboard.html |
| Taxes, Products + variants, Plans, Discount forms, styling, seed data, demo script | Teammate | routes_catalog.py, templates/products*, plans*, taxes*, static/style.css, seed.py |

## Progress checklist
- [x] Signup / login / reset / roles / add staff
- [ ] Taxes CRUD
- [ ] Products + variants CRUD
- [ ] Plans CRUD
- [ ] Discounts CRUD (admin only)
- [ ] Quotation templates
- [ ] Subscriptions + status flow
- [ ] Invoice generation (no double billing)
- [ ] Payments
- [ ] Customer portal
- [ ] Dashboard with real numbers
- [ ] Seed data + demo
