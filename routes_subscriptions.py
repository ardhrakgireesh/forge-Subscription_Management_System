"""Subscriptions: who buys which plan, from when to when.

Step 1: list, create (header only) and view one subscription.
Step 2: order lines (product, quantity, unit price, tax) and the totals.
Admin and staff can create. Customers will get their own portal later.
"""
import math
from datetime import datetime, date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from sqlalchemy.orm import joinedload, selectinload

from models import db, Subscription, SubscriptionLine, User, Plan, Product, ProductVariant, Tax
from helpers import login_required

subs_bp = Blueprint("subs", __name__)

PAYMENT_TERMS = ["Immediate", "15 days", "30 days", "45 days"]
STATUSES = ["Draft", "Quotation", "Confirmed", "Active", "Closed"]
# Lines can only be changed before the subscription is confirmed,
# otherwise the money on future invoices would change behind our back.
LINE_EDITABLE = ["Draft", "Quotation"]

# Status flow: Draft -> Quotation -> Confirmed -> Active -> Closed
# (a subscription can also be closed early, from any status before Closed)
NEXT_STEP = {
    "Draft": ("Quotation", "Send quotation"),
    "Quotation": ("Confirmed", "Confirm"),
    "Confirmed": ("Active", "Activate"),
}


def _parse_date(text):
    """'2026-11-30' -> a date. Empty text -> None. Bad text raises ValueError."""
    text = (text or "").strip()
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def _to_int(text):
    """'5' -> 5. Anything else -> None (so a bad value never crashes the page)."""
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def line_totals(line):
    """One line -> (amount before tax, tax amount). Billing will reuse this."""
    net = round(line.quantity * line.unit_price, 2)
    tax = round(net * line.tax.rate / 100, 2) if line.tax else 0.0
    return net, tax


def subscription_totals(sub):
    """All lines -> subtotal, tax and total of a subscription."""
    net = tax = 0.0
    for line in sub.lines:
        n, t = line_totals(line)
        net += n
        tax += t
    net, tax = round(net, 2), round(tax, 2)
    return {"net": net, "tax": tax, "total": round(net + tax, 2)}


def _read_form():
    """Checks every field of the form. Returns (clean_data, errors)."""
    f = request.form
    errors = []

    # Customer: must exist and must really be a customer (not staff or admin).
    customer = db.session.get(User, _to_int(f.get("customer_id"))) if _to_int(f.get("customer_id")) else None
    if not customer or customer.role != "customer":
        errors.append("Choose a customer.")

    # Plan: must exist.
    plan = db.session.get(Plan, _to_int(f.get("plan_id"))) if _to_int(f.get("plan_id")) else None
    if not plan:
        errors.append("Choose a plan.")

    # Dates: both required, expiry must come after start.
    start = expiry = None
    try:
        start = _parse_date(f.get("start_date"))
        expiry = _parse_date(f.get("expiry_date"))
    except ValueError:
        errors.append("Enter valid dates.")
    else:
        if not start:
            errors.append("Start date is required.")
        if not expiry:
            errors.append("Expiry date is required.")
        if start and expiry and expiry <= start:
            errors.append("Expiry date must be after the start date.")
        # The plan is only on sale between its own dates.
        if plan and start:
            if plan.start_date and start < plan.start_date:
                errors.append(f"This plan is only available from {plan.start_date:%d %b %Y}.")
            if plan.end_date and start > plan.end_date:
                errors.append(f"This plan ended on {plan.end_date:%d %b %Y}.")

    terms = f.get("payment_terms", "")
    if terms not in PAYMENT_TERMS:
        errors.append("Choose the payment terms.")

    data = dict(customer_id=customer.id if customer else None, plan_id=plan.id if plan else None,
                start_date=start, expiry_date=expiry, payment_terms=terms)
    return data, errors


def _form_page(f):
    """Shows the form with the customer and plan dropdowns filled."""
    customers = User.query.filter_by(role="customer").order_by(User.name).all()
    plans = Plan.query.order_by(Plan.name).all()
    return render_template("subscription_form.html", f=f, customers=customers, plans=plans,
                           terms=PAYMENT_TERMS)


@subs_bp.route("/subscriptions")
@login_required(["admin", "staff"])
def subscriptions():
    # Optional filter: /subscriptions?status=Active
    status = request.args.get("status", "")
    query = Subscription.query.options(joinedload(Subscription.customer), joinedload(Subscription.plan))
    if status in STATUSES:
        query = query.filter(Subscription.status == status)
    rows = query.order_by(Subscription.id.desc()).all()
    return render_template("subscriptions.html", rows=rows, statuses=STATUSES, status=status)


@subs_bp.route("/subscriptions/new", methods=["GET", "POST"])
@login_required(["admin", "staff"])
def subscription_new():
    if request.method == "POST":
        data, errors = _read_form()
        if errors:
            for e in errors:
                flash(e, "error")
            return _form_page(request.form.to_dict())
        sub = Subscription(status="Draft", **data)
        db.session.add(sub)
        db.session.flush()                      # gives the new row its id
        sub.number = f"SUB{sub.id:04d}"         # id 1 -> SUB0001
        db.session.commit()
        flash(f"Subscription {sub.number} created as a draft.", "ok")
        return redirect(url_for("subs.subscription_view", sub_id=sub.id))
    return _form_page({"payment_terms": "Immediate"})


def _view_page(sub):
    """Shows one subscription with its lines, totals and the add-line form."""
    products = Product.query.options(selectinload(Product.variants)).order_by(Product.name).all()
    variants = {v.id: v for p in products for v in p.variants}   # id -> variant, to print names
    taxes = Tax.query.order_by(Tax.name).all()
    return render_template("subscription_view.html", s=sub, products=products, variants=variants,
                           taxes=taxes, totals=subscription_totals(sub),
                           line_totals=line_totals, editable=sub.status in LINE_EDITABLE,
                           next_step=NEXT_STEP.get(sub.status),
                           can_close=sub.status != "Closed")


@subs_bp.route("/subscriptions/<int:sub_id>")
@login_required(["admin", "staff"])
def subscription_view(sub_id):
    sub = db.session.get(Subscription, sub_id) or abort(404)
    return _view_page(sub)


@subs_bp.route("/subscriptions/<int:sub_id>/lines/add", methods=["POST"])
@login_required(["admin", "staff"])
def line_add(sub_id):
    sub = db.session.get(Subscription, sub_id) or abort(404)
    back = redirect(url_for("subs.subscription_view", sub_id=sub.id))
    if sub.status not in LINE_EDITABLE:
        flash("Lines can only be changed while the subscription is a Draft or Quotation.", "error")
        return back

    f = request.form
    errors = []

    # Product (and optional variant). The dropdown sends "productId:variantId", e.g. "3:7" or "3:0".
    product = variant = None
    try:
        product_id, variant_id = (int(x) for x in f.get("item", "").split(":"))
    except ValueError:
        product_id = variant_id = 0
    product = db.session.get(Product, product_id) if product_id else None
    if not product:
        errors.append("Choose a product.")
    elif variant_id:
        variant = db.session.get(ProductVariant, variant_id)
        if not variant or variant.product_id != product.id:
            errors.append("Choose a valid option for this product.")
            variant = None

    # Quantity: whole number, at least the plan's minimum.
    minimum = sub.plan.min_quantity or 1
    qty = _to_int(f.get("quantity", "").strip())
    if qty is None or qty < 1:
        errors.append("Quantity must be a whole number, 1 or more.")
    elif qty < minimum:
        errors.append(f"The minimum quantity for this plan is {minimum}.")
    elif qty > 100000:
        errors.append("Quantity is too large.")

    # Unit price: empty means "use the catalog price" (product price + variant extra).
    price_text = f.get("unit_price", "").strip()
    price = None
    if price_text == "":
        if product:
            price = product.sales_price + (variant.extra_price or 0 if variant else 0)
    else:
        try:
            price = float(price_text)
            if not math.isfinite(price) or price < 0:
                errors.append("Unit price cannot be negative.")
            elif price > 10_000_000:
                errors.append("Unit price is too large.")
        except ValueError:
            errors.append("Unit price must be a number, like 499.")

    # Tax: optional.
    tax = None
    if f.get("tax_id", "").strip():
        tax = db.session.get(Tax, _to_int(f.get("tax_id")) or 0)
        if not tax:
            errors.append("Choose a valid tax.")

    # The same product + option cannot be added twice.
    if product and not errors:
        same = SubscriptionLine.query.filter_by(subscription_id=sub.id, product_id=product.id,
                                                variant_id=variant.id if variant else None).first()
        if same:
            errors.append("This product is already on the subscription. Remove it first to change it.")

    if errors:
        for e in errors:
            flash(e, "error")
        return back

    db.session.add(SubscriptionLine(subscription_id=sub.id, product_id=product.id,
                                    variant_id=variant.id if variant else None, quantity=qty,
                                    unit_price=round(price, 2), tax_id=tax.id if tax else None))
    db.session.commit()
    flash("Line added.", "ok")
    return back


@subs_bp.route("/subscriptions/<int:sub_id>/lines/<int:line_id>/delete", methods=["POST"])
@login_required(["admin", "staff"])
def line_delete(sub_id, line_id):
    sub = db.session.get(Subscription, sub_id) or abort(404)
    line = db.session.get(SubscriptionLine, line_id)
    if not line or line.subscription_id != sub.id:
        abort(404)
    if sub.status not in LINE_EDITABLE:
        flash("Lines can only be changed while the subscription is a Draft or Quotation.", "error")
    else:
        db.session.delete(line)
        db.session.commit()
        flash("Line removed.", "ok")
    return redirect(url_for("subs.subscription_view", sub_id=sub.id))


@subs_bp.route("/subscriptions/<int:sub_id>/status", methods=["POST"])
@login_required(["admin", "staff"])
def subscription_status(sub_id):
    """Moves a subscription to its next status (or closes it)."""
    sub = db.session.get(Subscription, sub_id) or abort(404)
    to = request.form.get("to", "")
    back = redirect(url_for("subs.subscription_view", sub_id=sub.id))

    step = NEXT_STEP.get(sub.status)
    if to == "Closed" and sub.status != "Closed":
        # A plan can forbid closing early (the admin decides plan by plan).
        if sub.status == "Active" and not sub.plan.closable and (not sub.expiry_date or sub.expiry_date >= date.today()):
            flash("This plan cannot be closed early.", "error")
            return back
        sub.status, sub.next_invoice_date = "Closed", None
        db.session.commit()
        flash(f"{sub.number} is now Closed.", "ok")
        return back

    if not step or to != step[0]:
        flash("That status change is not allowed.", "error")
        return back
    if not sub.lines:
        flash("Add at least one order line first.", "error")
        return back
    if to == "Active":
        if sub.expiry_date and sub.expiry_date < date.today():
            flash("The expiry date has already passed, so this subscription cannot be activated.", "error")
            return back
        sub.next_invoice_date = sub.start_date      # the first invoice is due on the start date
    sub.status = to
    db.session.commit()
    flash(f"{sub.number} is now {to}.", "ok")
    return back
