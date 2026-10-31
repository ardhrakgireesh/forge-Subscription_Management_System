"""Database tables for the Subscription Management System.

Everything lives in a local SQLite file, so it works offline.
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)  # one account per email
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")  # admin / staff / customer
    reset_token = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Tax(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)      # e.g. GST 18%
    rate = db.Column(db.Float, nullable=False)           # percent, e.g. 18


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), default="Service")
    sales_price = db.Column(db.Float, nullable=False)
    cost_price = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)
    variants = db.relationship("ProductVariant", backref="product", cascade="all, delete-orphan")


class ProductVariant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    attribute = db.Column(db.String(50), nullable=False)  # e.g. Brand
    value = db.Column(db.String(50), nullable=False)      # e.g. Odoo
    extra_price = db.Column(db.Float, default=0)          # e.g. +560


class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    billing_period = db.Column(db.String(10), nullable=False)  # daily/weekly/monthly/yearly
    min_quantity = db.Column(db.Integer, default=1)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    auto_close = db.Column(db.Boolean, default=False)
    closable = db.Column(db.Boolean, default=True)
    pausable = db.Column(db.Boolean, default=True)
    renewable = db.Column(db.Boolean, default=True)


class Discount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    kind = db.Column(db.String(10), nullable=False)       # fixed / percent
    value = db.Column(db.Float, nullable=False)
    min_purchase = db.Column(db.Float, default=0)
    min_quantity = db.Column(db.Integer, default=0)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    usage_limit = db.Column(db.Integer)                   # None = unlimited
    times_used = db.Column(db.Integer, default=0)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"))  # None = whole subscription


class QuotationTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("plan.id"))
    validity_days = db.Column(db.Integer, default=30)
    plan = db.relationship("Plan")
    lines = db.relationship("TemplateLine", backref="template", cascade="all, delete-orphan")


class TemplateLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("quotation_template.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    product = db.relationship("Product")


class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True)        # SUB0001
    customer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("plan.id"), nullable=False)
    start_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    payment_terms = db.Column(db.String(50), default="Immediate")
    # Draft -> Quotation -> Confirmed -> Active -> Closed
    status = db.Column(db.String(20), default="Draft")
    next_invoice_date = db.Column(db.Date)
    customer = db.relationship("User")
    plan = db.relationship("Plan")
    lines = db.relationship("SubscriptionLine", backref="subscription", cascade="all, delete-orphan")


class SubscriptionLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey("subscription.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id"))
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    tax_id = db.Column(db.Integer, db.ForeignKey("tax.id"))
    product = db.relationship("Product")
    tax = db.relationship("Tax")


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True)        # INV0001
    subscription_id = db.Column(db.Integer, db.ForeignKey("subscription.id"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default="Draft")    # Draft -> Confirmed -> Paid (or Cancelled)
    subtotal = db.Column(db.Float, default=0)
    discount_total = db.Column(db.Float, default=0)
    tax_total = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)
    subscription = db.relationship("Subscription")
    customer = db.relationship("User")
    lines = db.relationship("InvoiceLine", backref="invoice", cascade="all, delete-orphan")
    payments = db.relationship("Payment", backref="invoice")
    # Nothing is billed twice: one invoice per subscription per period.
    __table_args__ = (db.UniqueConstraint("subscription_id", "period_start", name="uq_sub_period"),)


class InvoiceLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False)
    description = db.Column(db.String(200))
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, default=0)
    tax_amount = db.Column(db.Float, default=0)
    amount = db.Column(db.Float, default=0)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False)
    method = db.Column(db.String(30), nullable=False)     # Cash / UPI / Card / Bank
    amount = db.Column(db.Float, nullable=False)
    paid_on = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(200))
