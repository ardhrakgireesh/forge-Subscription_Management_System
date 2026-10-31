"""Fills the database with realistic demo data.  Run:  py seed.py

Safe to run twice: everything is checked first (by email, name or customer + plan),
so nothing is added a second time. The admin user is never touched.
Dates are relative to today, so overdue invoices are always overdue on demo day.
"""
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from app import app, init_db
from models import (db, User, Tax, Product, ProductVariant, Plan, Discount,
                    Subscription, SubscriptionLine, Invoice, Payment)
from billing import run_billing

init_db()        # makes sure the tables and the admin user exist
today = date.today()
D = lambda days: today + timedelta(days=days)        # D(-30) = 30 days ago

CUSTOMERS = [
    ("Sharma Traders", "sharma@sharmatraders.in"),
    ("Patel Electronics", "accounts@patelelectronics.in"),
    ("Gupta Foods", "info@guptafoods.in"),
    ("Nair Bakery", "hello@nairbakery.in"),
    ("Reddy Logistics", "billing@reddylogistics.in"),
    ("Iyer Textiles", "office@iyertextiles.in"),
    ("Menon Pharma", "finance@menonpharma.in"),
    ("Das Studio", "contact@dasstudio.in"),
]
# name, type, sales price, cost price, [(attribute, value, extra price)]
PRODUCTS = [
    ("Accounting Suite", "Software", 1000, 400, [("Brand", "Odoo", 560), ("Brand", "Tally", 300)]),
    ("CRM Pro", "Software", 1500, 600, [("Brand", "Odoo", 560)]),
    ("Support Add-on", "Add-on", 250, 80, []),
    ("Extra Storage", "Add-on", 150, 40, []),
    ("Onboarding Service", "Service", 5000, 2000, []),
]
# name, price, period, min qty, end date, auto close
PLANS = [
    ("Monthly Standard", 1500, "monthly", 1, None, False),
    ("Yearly Business", 15000, "yearly", 1, None, False),
    ("Weekly Starter", 300, "weekly", 1, None, False),
    ("Seasonal Promo", 800, "monthly", 1, D(60), True),
]
# customer email, plan, status, start, expiry, terms, [(product, variant value, qty, tax)]
SUBSCRIPTIONS = [
    ("sharma@sharmatraders.in", "Monthly Standard", "Active", D(-75), D(290), "15 days",
     [("Accounting Suite", "Odoo", 2, "GST 18%"), ("Support Add-on", None, 2, "GST 18%")]),
    ("accounts@patelelectronics.in", "Yearly Business", "Active", D(-200), D(165), "30 days",
     [("CRM Pro", "Odoo", 5, "GST 18%")]),
    ("info@guptafoods.in", "Weekly Starter", "Active", D(-21), D(340), "Immediate",
     [("Extra Storage", None, 3, "GST 5%")]),
    ("hello@nairbakery.in", "Monthly Standard", "Active", D(-40), D(325), "Immediate",
     [("Accounting Suite", None, 1, "GST 18%")]),
    ("billing@reddylogistics.in", "Monthly Standard", "Active", D(-95), D(5), "15 days",
     [("Accounting Suite", "Tally", 3, "GST 18%")]),
    ("office@iyertextiles.in", "Seasonal Promo", "Active", D(-10), D(50), "Immediate",
     [("Support Add-on", None, 4, "GST 18%")]),
    ("finance@menonpharma.in", "Monthly Standard", "Confirmed", D(5), D(370), "30 days",
     [("CRM Pro", None, 2, "GST 18%")]),
    ("contact@dasstudio.in", "Yearly Business", "Quotation", D(10), D(375), "45 days",
     [("Onboarding Service", None, 1, "GST 18%"), ("CRM Pro", "Odoo", 1, "GST 18%")]),
    ("sharma@sharmatraders.in", "Weekly Starter", "Draft", D(14), D(200), "Immediate",
     [("Extra Storage", None, 2, "GST 5%")]),
    ("hello@nairbakery.in", "Seasonal Promo", "Closed", D(-200), D(-20), "Immediate",
     [("Support Add-on", None, 1, "GST 18%")]),
]
SLOW_PAYERS = {"billing@reddylogistics.in", "hello@nairbakery.in", "info@guptafoods.in"}  # these stay overdue
METHODS = ["UPI", "Bank", "Card", "Cash"]


def lower_name(model, name):
    return model.query.filter(db.func.lower(model.name) == name.lower()).first()


with app.app_context():
    # ---------- taxes ----------
    for name, rate in [("GST 18%", 18), ("GST 5%", 5)]:
        if not lower_name(Tax, name):
            db.session.add(Tax(name=name, rate=rate))

    # ---------- staff and customers ----------
    if not User.query.filter_by(email="staff@brightloop.com").first():
        db.session.add(User(name="Priya Staff", email="staff@brightloop.com", role="staff",
                            password_hash=generate_password_hash("Staff@12345!")))
    for name, email in CUSTOMERS:
        if not User.query.filter_by(email=email).first():
            db.session.add(User(name=name, email=email, role="customer",
                                password_hash=generate_password_hash("Customer@123!")))
    db.session.commit()

    # ---------- products and variants ----------
    for name, ptype, sales, cost, variants in PRODUCTS:
        product = lower_name(Product, name)
        if not product:
            product = Product(name=name, type=ptype, sales_price=sales, cost_price=cost)
            db.session.add(product)
            db.session.flush()
        for attribute, value, extra in variants:
            if not ProductVariant.query.filter_by(product_id=product.id, attribute=attribute, value=value).first():
                db.session.add(ProductVariant(product_id=product.id, attribute=attribute, value=value,
                                              extra_price=extra))
    db.session.commit()

    # ---------- plans ----------
    for name, price, period, minimum, end, auto in PLANS:
        if not lower_name(Plan, name):
            db.session.add(Plan(name=name, price=price, billing_period=period, min_quantity=minimum,
                                end_date=end, auto_close=auto))
    db.session.commit()

    # ---------- discounts ----------
    if not lower_name(Discount, "Volume discount 10%"):
        db.session.add(Discount(name="Volume discount 10%", kind="percent", value=10, min_quantity=5,
                                usage_limit=100))
    if not lower_name(Discount, "Storage offer ₹100 off"):
        storage = lower_name(Product, "Extra Storage")
        db.session.add(Discount(name="Storage offer ₹100 off", kind="fixed", value=100,
                                end_date=D(120), usage_limit=50, product_id=storage.id))
    db.session.commit()

    # ---------- subscriptions ----------
    new_subs = 0
    for email, plan_name, status, start, expiry, terms, lines in SUBSCRIPTIONS:
        customer = User.query.filter_by(email=email).first()
        plan = lower_name(Plan, plan_name)
        if Subscription.query.filter_by(customer_id=customer.id, plan_id=plan.id).first():
            continue                                        # already seeded
        sub = Subscription(customer_id=customer.id, plan_id=plan.id, status=status, start_date=start,
                           expiry_date=expiry, payment_terms=terms,
                           next_invoice_date=start if status == "Active" else None)
        db.session.add(sub)
        db.session.flush()
        sub.number = f"SUB{sub.id:04d}"
        for product_name, variant_value, qty, tax_name in lines:
            product = lower_name(Product, product_name)
            variant = (ProductVariant.query.filter_by(product_id=product.id, value=variant_value).first()
                       if variant_value else None)
            price = product.sales_price + (variant.extra_price if variant else 0)
            db.session.add(SubscriptionLine(subscription_id=sub.id, product_id=product.id,
                                            variant_id=variant.id if variant else None, quantity=qty,
                                            unit_price=price, tax_id=lower_name(Tax, tax_name).id))
        new_subs += 1
    db.session.commit()

    # ---------- invoices: use the real billing engine, so totals, tax and discounts are correct ----------
    stats = run_billing(today)

    # ---------- give the new (Draft) invoices a realistic status and payments ----------
    seed_ids = [u.id for u in User.query.filter(User.email.in_([c[1] for c in CUSTOMERS])).all()]
    slow_ids = {u.id for u in User.query.filter(User.email.in_(SLOW_PAYERS)).all()}
    new_payments = 0
    drafts = (Invoice.query.filter(Invoice.status == "Draft", Invoice.customer_id.in_(seed_ids))
              .order_by(Invoice.id).all())
    for i, inv in enumerate(drafts):
        inv.status = "Confirmed"
        age = (today - inv.due_date).days                  # days late (negative = not due yet)
        pay_in_full = (age > 45) or (age > 0 and inv.customer_id not in slow_ids)
        if pay_in_full:
            inv.status = "Paid"
            db.session.add(Payment(invoice_id=inv.id, method=METHODS[i % 4], amount=inv.total,
                                   paid_on=min(inv.due_date + timedelta(days=3), today), note="Seed payment"))
            new_payments += 1
    # one part-paid invoice, so the demo shows "balance" working
    part = (Invoice.query.filter(Invoice.status == "Confirmed", Invoice.customer_id.in_(slow_ids),
                                 Invoice.due_date < today).order_by(Invoice.due_date.desc()).first())
    if part and not part.payments:
        db.session.add(Payment(invoice_id=part.id, method="UPI", amount=round(part.total / 2, 2),
                               paid_on=today - timedelta(days=2), note="Seed payment (part)"))
        new_payments += 1
    db.session.commit()

    print("Seed finished.")
    print(f"  New subscriptions: {new_subs}")
    print(f"  Invoices created:  {stats['created']}   Payments added: {new_payments}")
    print(f"  Totals now: {User.query.filter_by(role='customer').count()} customers, "
          f"{Product.query.count()} products, {Plan.query.count()} plans, "
          f"{Subscription.query.count()} subscriptions, {Invoice.query.count()} invoices, "
          f"{Payment.query.count()} payments")
