"""Quotation templates: a ready-made plan + product lines a sales rep can turn into a subscription.

Admin builds templates. Admin and staff can use one to create a subscription (status Quotation).
"""
from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from sqlalchemy.orm import selectinload

from models import db, QuotationTemplate, TemplateLine, Plan, Product, Tax, User, Subscription, SubscriptionLine
from helpers import login_required
from routes_subscriptions import _parse_date, _to_int, PAYMENT_TERMS

qt_bp = Blueprint("qt", __name__)


def _view_page(t, form=None):
    products = Product.query.order_by(Product.name).all()
    customers = User.query.filter_by(role="customer").order_by(User.name).all()
    taxes = Tax.query.order_by(Tax.name).all()
    form = form or {"start_date": date.today().isoformat(),
                    "expiry_date": (date.today() + timedelta(days=365)).isoformat(),
                    "payment_terms": "Immediate"}
    return render_template("qtemplate_view.html", t=t, products=products, customers=customers,
                           taxes=taxes, terms=PAYMENT_TERMS, f=form)


def _read_template_form(template_id=None):
    name = request.form.get("name", "").strip()
    errors = []
    if not name:
        errors.append("Template name is required.")
    elif len(name) > 100:
        errors.append("Template name must be 100 characters or less.")
    else:
        same = QuotationTemplate.query.filter(db.func.lower(QuotationTemplate.name) == name.lower())
        if template_id:
            same = same.filter(QuotationTemplate.id != template_id)
        if same.first():
            errors.append("A template with this name already exists.")

    plan = db.session.get(Plan, _to_int(request.form.get("plan_id")) or 0)
    if not plan:
        errors.append("Choose a plan.")

    days = _to_int(request.form.get("validity_days", "").strip())
    if days is None or days < 1 or days > 365:
        errors.append("Validity must be a whole number of days, from 1 to 365.")
    return name, plan, days, errors


@qt_bp.route("/quotation-templates")
@login_required(["admin", "staff"])
def templates():
    rows = QuotationTemplate.query.options(selectinload(QuotationTemplate.plan),
                                           selectinload(QuotationTemplate.lines)).order_by(QuotationTemplate.name).all()
    return render_template("qtemplates.html", rows=rows)


@qt_bp.route("/quotation-templates/new", methods=["GET", "POST"])
@login_required(["admin"])
def template_new():
    plans = Plan.query.order_by(Plan.name).all()
    if request.method == "POST":
        name, plan, days, errors = _read_template_form()
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("qtemplate_form.html", plans=plans, f=request.form.to_dict())
        t = QuotationTemplate(name=name, plan_id=plan.id, validity_days=days)
        db.session.add(t)
        db.session.commit()
        flash("Template created. Now add its product lines.", "ok")
        return redirect(url_for("qt.template_view", t_id=t.id))
    return render_template("qtemplate_form.html", plans=plans, f={"validity_days": 30})


@qt_bp.route("/quotation-templates/<int:t_id>")
@login_required(["admin", "staff"])
def template_view(t_id):
    t = db.session.get(QuotationTemplate, t_id) or abort(404)
    return _view_page(t)


@qt_bp.route("/quotation-templates/<int:t_id>/delete", methods=["POST"])
@login_required(["admin"])
def template_delete(t_id):
    t = db.session.get(QuotationTemplate, t_id) or abort(404)
    db.session.delete(t)
    db.session.commit()
    flash("Template deleted.", "ok")
    return redirect(url_for("qt.templates"))


@qt_bp.route("/quotation-templates/<int:t_id>/lines/add", methods=["POST"])
@login_required(["admin"])
def template_line_add(t_id):
    t = db.session.get(QuotationTemplate, t_id) or abort(404)
    errors = []
    product = db.session.get(Product, _to_int(request.form.get("product_id")) or 0)
    if not product:
        errors.append("Choose a product.")
    elif TemplateLine.query.filter_by(template_id=t.id, product_id=product.id).first():
        errors.append("This product is already in the template.")
    qty = _to_int(request.form.get("quantity", "").strip())
    if qty is None or qty < 1 or qty > 100000:
        errors.append("Quantity must be a whole number, 1 or more.")
    if errors:
        for e in errors:
            flash(e, "error")
    else:
        db.session.add(TemplateLine(template_id=t.id, product_id=product.id, quantity=qty))
        db.session.commit()
        flash("Line added.", "ok")
    return redirect(url_for("qt.template_view", t_id=t.id))


@qt_bp.route("/quotation-templates/<int:t_id>/lines/<int:line_id>/delete", methods=["POST"])
@login_required(["admin"])
def template_line_delete(t_id, line_id):
    line = db.session.get(TemplateLine, line_id)
    if not line or line.template_id != t_id:
        abort(404)
    db.session.delete(line)
    db.session.commit()
    flash("Line removed.", "ok")
    return redirect(url_for("qt.template_view", t_id=t_id))


@qt_bp.route("/quotation-templates/<int:t_id>/use", methods=["POST"])
@login_required(["admin", "staff"])
def template_use(t_id):
    """Creates a new subscription (status Quotation) from the template."""
    t = db.session.get(QuotationTemplate, t_id) or abort(404)
    f = request.form
    errors = []

    if not t.plan:
        errors.append("This template has no plan.")
    if not t.lines:
        errors.append("This template has no product lines yet.")

    customer = db.session.get(User, _to_int(f.get("customer_id")) or 0)
    if not customer or customer.role != "customer":
        errors.append("Choose a customer.")

    start = expiry = None
    try:
        start, expiry = _parse_date(f.get("start_date")), _parse_date(f.get("expiry_date"))
    except ValueError:
        errors.append("Enter valid dates.")
    else:
        if not start or not expiry:
            errors.append("Start date and expiry date are required.")
        elif expiry <= start:
            errors.append("Expiry date must be after the start date.")
        elif t.plan:
            if t.plan.start_date and start < t.plan.start_date:
                errors.append(f"This plan is only available from {t.plan.start_date:%d %b %Y}.")
            if t.plan.end_date and start > t.plan.end_date:
                errors.append(f"This plan ended on {t.plan.end_date:%d %b %Y}.")

    terms = f.get("payment_terms", "")
    if terms not in PAYMENT_TERMS:
        errors.append("Choose the payment terms.")

    tax = None
    if f.get("tax_id", "").strip():
        tax = db.session.get(Tax, _to_int(f.get("tax_id")) or 0)
        if not tax:
            errors.append("Choose a valid tax.")

    if errors:
        for e in errors:
            flash(e, "error")
        return _view_page(t, f.to_dict())

    sub = Subscription(status="Quotation", customer_id=customer.id, plan_id=t.plan_id,
                       start_date=start, expiry_date=expiry, payment_terms=terms)
    db.session.add(sub)
    db.session.flush()
    sub.number = f"SUB{sub.id:04d}"
    minimum = t.plan.min_quantity or 1
    for l in t.lines:
        db.session.add(SubscriptionLine(subscription_id=sub.id, product_id=l.product_id,
                                        quantity=max(l.quantity or 1, minimum),
                                        unit_price=round(l.product.sales_price, 2),
                                        tax_id=tax.id if tax else None))
    db.session.commit()
    valid_until = date.today() + timedelta(days=t.validity_days or 30)
    flash(f"Quotation {sub.number} created from “{t.name}”. The offer is valid until {valid_until:%d %b %Y}.", "ok")
    return redirect(url_for("subs.subscription_view", sub_id=sub.id))
