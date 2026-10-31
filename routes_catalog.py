"""Catalog pages: Taxes, Products (with variants) and Discounts.
(Plans live in routes_plans.py.)

PATTERN used for every page (copy the Tax code below and rename):
  1. a LIST route      -> shows a table
  2. a NEW route       -> shows a form (GET) and saves it (POST)
  3. an EDIT route     -> same form, filled in
  4. a DELETE route    -> POST only
Only the admin can add / edit / delete. Staff can only look.
"""
import math
from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from sqlalchemy.orm import selectinload

from models import (db, Tax, SubscriptionLine, Product, ProductVariant, Discount, TemplateLine)
from helpers import login_required

catalog_bp = Blueprint("catalog", __name__)


# =====================================================================
#  TAXES
# =====================================================================
def _read_tax_form(tax_id=None):
    """Reads the form, checks every field, returns (name, rate, errors)."""
    name = request.form.get("name", "").strip()
    rate_text = request.form.get("rate", "").strip()
    errors = []

    if not name:
        errors.append("Tax name is required.")
    elif len(name) > 50:
        errors.append("Tax name must be 50 characters or less.")
    else:
        same = Tax.query.filter(db.func.lower(Tax.name) == name.lower())
        if tax_id:
            same = same.filter(Tax.id != tax_id)
        if same.first():
            errors.append("A tax with this name already exists.")

    rate = None
    try:
        rate = float(rate_text)
        if rate < 0 or rate > 100:
            errors.append("Rate must be between 0 and 100.")
    except ValueError:
        errors.append("Rate must be a number, like 18.")

    return name, rate, errors


@catalog_bp.route("/taxes")
@login_required(["admin", "staff"])
def taxes():
    all_taxes = Tax.query.order_by(Tax.name).all()
    return render_template("taxes.html", taxes=all_taxes)


@catalog_bp.route("/taxes/new", methods=["GET", "POST"])
@login_required(["admin"])
def tax_new():
    if request.method == "POST":
        name, rate, errors = _read_tax_form()
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("tax_form.html", tax=None,
                                   name=name, rate=request.form.get("rate", ""))
        db.session.add(Tax(name=name, rate=rate))
        db.session.commit()
        flash("Tax added.", "ok")
        return redirect(url_for("catalog.taxes"))
    return render_template("tax_form.html", tax=None, name="", rate="")


@catalog_bp.route("/taxes/<int:tax_id>/edit", methods=["GET", "POST"])
@login_required(["admin"])
def tax_edit(tax_id):
    tax = db.session.get(Tax, tax_id) or abort(404)
    if request.method == "POST":
        name, rate, errors = _read_tax_form(tax_id)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("tax_form.html", tax=tax,
                                   name=name, rate=request.form.get("rate", ""))
        tax.name, tax.rate = name, rate
        db.session.commit()
        flash("Tax updated.", "ok")
        return redirect(url_for("catalog.taxes"))
    return render_template("tax_form.html", tax=tax, name=tax.name, rate=tax.rate)


@catalog_bp.route("/taxes/<int:tax_id>/delete", methods=["POST"])
@login_required(["admin"])
def tax_delete(tax_id):
    tax = db.session.get(Tax, tax_id) or abort(404)
    if SubscriptionLine.query.filter_by(tax_id=tax.id).first():
        flash("This tax is used in a subscription, so it cannot be deleted.", "error")
    else:
        db.session.delete(tax)
        db.session.commit()
        flash("Tax deleted.", "ok")
    return redirect(url_for("catalog.taxes"))


# =====================================================================
#  SMALL CHECKING HELPERS (used by Products and Discounts)
# =====================================================================
def _number(text, label, errors, required=False, minimum=0, maximum=10_000_000, whole=False):
    """Turns text into a number. Adds a message to `errors` if it is wrong. Returns the number or None."""
    text = (text or "").strip()
    if text == "":
        if required:
            errors.append(f"{label} is required.")
        return None
    try:
        value = int(text) if whole else float(text)
    except ValueError:
        errors.append(f"{label} must be {'a whole number' if whole else 'a number'}, like 500.")
        return None
    if not whole and not math.isfinite(value):
        errors.append(f"{label} must be a normal number.")
        return None
    if value < minimum:
        errors.append(f"{label} cannot be less than {minimum:g}.")
        return None
    if value > maximum:
        errors.append(f"{label} is too large.")
        return None
    return value if whole else round(value, 2)


def _date(text, label, errors):
    """'2026-11-30' -> date. Empty -> None. Wrong text adds an error."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"{label} is not a valid date.")
        return None


# =====================================================================
#  PRODUCTS
# =====================================================================
PRODUCT_TYPES = ["Service", "Software", "Add-on", "Hardware"]


def _read_product_form(product_id=None):
    """Reads and checks the product form. Returns (data, errors)."""
    f = request.form
    errors = []

    name = f.get("name", "").strip()
    if not name:
        errors.append("Product name is required.")
    elif len(name) > 100:
        errors.append("Product name must be 100 characters or less.")
    else:
        same = Product.query.filter(db.func.lower(Product.name) == name.lower())
        if product_id:
            same = same.filter(Product.id != product_id)
        if same.first():
            errors.append("A product with this name already exists.")

    ptype = f.get("type", "")
    if ptype not in PRODUCT_TYPES:                      # never trust the browser
        errors.append("Choose a valid product type.")

    sales = _number(f.get("sales_price"), "Sales price", errors, required=True)
    cost = _number(f.get("cost_price"), "Cost price", errors)
    notes = f.get("notes", "").strip()
    if len(notes) > 500:
        errors.append("Notes must be 500 characters or less.")

    return dict(name=name, type=ptype, sales_price=sales, cost_price=cost or 0, notes=notes), errors


@catalog_bp.route("/products")
@login_required(["admin", "staff"])
def products():
    rows = Product.query.options(selectinload(Product.variants)).order_by(Product.name).all()
    return render_template("products.html", rows=rows)


@catalog_bp.route("/products/new", methods=["GET", "POST"])
@login_required(["admin"])
def product_new():
    if request.method == "POST":
        data, errors = _read_product_form()
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("product_form.html", product=None, f=request.form.to_dict(), types=PRODUCT_TYPES)
        db.session.add(Product(**data))
        db.session.commit()
        flash("Product added.", "ok")
        return redirect(url_for("catalog.products"))
    return render_template("product_form.html", product=None, f={}, types=PRODUCT_TYPES)


@catalog_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required(["admin"])
def product_edit(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    if request.method == "POST":
        data, errors = _read_product_form(product_id)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("product_form.html", product=product, f=request.form.to_dict(), types=PRODUCT_TYPES)
        for key, value in data.items():
            setattr(product, key, value)
        db.session.commit()
        flash("Product updated.", "ok")
        return redirect(url_for("catalog.product_edit", product_id=product.id))
    f = dict(name=product.name, type=product.type, sales_price=product.sales_price,
             cost_price=product.cost_price, notes=product.notes or "")
    return render_template("product_form.html", product=product, f=f, types=PRODUCT_TYPES)


@catalog_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required(["admin"])
def product_delete(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    # Delete safety: never delete something that other records use.
    if SubscriptionLine.query.filter_by(product_id=product.id).first():
        flash("This product is used in a subscription, so it cannot be deleted.", "error")
    elif TemplateLine.query.filter_by(product_id=product.id).first():
        flash("This product is used in a quotation template, so it cannot be deleted.", "error")
    elif Discount.query.filter_by(product_id=product.id).first():
        flash("This product is used by a discount, so it cannot be deleted.", "error")
    else:
        db.session.delete(product)
        db.session.commit()
        flash("Product deleted.", "ok")
    return redirect(url_for("catalog.products"))


# ---------- variants: for example Brand = Odoo adds 560 to the price ----------
@catalog_bp.route("/products/<int:product_id>/variants/add", methods=["POST"])
@login_required(["admin"])
def variant_add(product_id):
    product = db.session.get(Product, product_id) or abort(404)
    attribute = request.form.get("attribute", "").strip()
    value = request.form.get("value", "").strip()
    errors = []

    if not attribute:
        errors.append("Attribute is required (for example Brand).")
    elif len(attribute) > 50:
        errors.append("Attribute must be 50 characters or less.")
    if not value:
        errors.append("Value is required (for example Odoo).")
    elif len(value) > 50:
        errors.append("Value must be 50 characters or less.")

    extra = _number(request.form.get("extra_price"), "Extra price", errors, required=True)

    if attribute and value and not errors:
        for v in product.variants:                      # same attribute + value cannot be added twice
            if v.attribute.lower() == attribute.lower() and v.value.lower() == value.lower():
                errors.append("This variant already exists for this product.")
                break

    if errors:
        for e in errors:
            flash(e, "error")
    else:
        db.session.add(ProductVariant(product_id=product.id, attribute=attribute, value=value, extra_price=extra))
        db.session.commit()
        flash("Variant added.", "ok")
    return redirect(url_for("catalog.product_edit", product_id=product.id))


@catalog_bp.route("/products/<int:product_id>/variants/<int:variant_id>/delete", methods=["POST"])
@login_required(["admin"])
def variant_delete(product_id, variant_id):
    variant = db.session.get(ProductVariant, variant_id)
    if not variant or variant.product_id != product_id:
        abort(404)
    if SubscriptionLine.query.filter_by(variant_id=variant.id).first():
        flash("This variant is used in a subscription, so it cannot be deleted.", "error")
    else:
        db.session.delete(variant)
        db.session.commit()
        flash("Variant deleted.", "ok")
    return redirect(url_for("catalog.product_edit", product_id=product_id))


# =====================================================================
#  DISCOUNTS (admin only, even the list)
# =====================================================================
DISCOUNT_KINDS = ["fixed", "percent"]


def discount_status(d, today=None):
    """Expired / Used up / Active, worked out when the page is shown."""
    today = today or date.today()
    if d.end_date and d.end_date < today:
        return "Expired"
    if d.usage_limit is not None and (d.times_used or 0) >= d.usage_limit:
        return "Used up"
    return "Active"


def _read_discount_form():
    f = request.form
    errors = []

    name = f.get("name", "").strip()
    if not name:
        errors.append("Discount name is required.")
    elif len(name) > 100:
        errors.append("Discount name must be 100 characters or less.")

    kind = f.get("kind", "")
    if kind not in DISCOUNT_KINDS:
        errors.append("Choose fixed or percent.")

    value = _number(f.get("value"), "Value", errors, required=True)
    if value is not None:
        if value <= 0:
            errors.append("Value must be above 0.")
        elif kind == "percent" and value > 100:
            errors.append("A percent discount cannot be more than 100.")

    min_purchase = _number(f.get("min_purchase"), "Minimum purchase", errors)
    min_quantity = _number(f.get("min_quantity"), "Minimum quantity", errors, whole=True)
    usage_limit = _number(f.get("usage_limit"), "Usage limit", errors, whole=True, minimum=1)

    start = _date(f.get("start_date"), "Start date", errors)
    end = _date(f.get("end_date"), "End date", errors)
    if start and end and end < start:
        errors.append("End date cannot be before the start date.")

    product = None
    if f.get("product_id", "").strip():
        try:
            product = db.session.get(Product, int(f.get("product_id")))
        except ValueError:
            product = None
        if not product:
            errors.append("Choose a valid product.")

    data = dict(name=name, kind=kind, value=value, min_purchase=min_purchase or 0,
                min_quantity=min_quantity or 0, usage_limit=usage_limit,
                start_date=start, end_date=end, product_id=product.id if product else None)
    return data, errors


def _discount_page(discount, f):
    return render_template("discount_form.html", discount=discount, f=f, kinds=DISCOUNT_KINDS,
                           products=Product.query.order_by(Product.name).all())


@catalog_bp.route("/discounts")
@login_required(["admin"])
def discounts():
    rows = Discount.query.order_by(Discount.id.desc()).all()
    names = {p.id: p.name for p in Product.query.all()}
    today = date.today()
    return render_template("discounts.html", rows=rows, names=names,
                           status_of=lambda d: discount_status(d, today))


@catalog_bp.route("/discounts/new", methods=["GET", "POST"])
@login_required(["admin"])
def discount_new():
    if request.method == "POST":
        data, errors = _read_discount_form()
        if errors:
            for e in errors:
                flash(e, "error")
            return _discount_page(None, request.form.to_dict())
        db.session.add(Discount(**data))
        db.session.commit()
        flash("Discount added.", "ok")
        return redirect(url_for("catalog.discounts"))
    return _discount_page(None, {"kind": "percent"})


@catalog_bp.route("/discounts/<int:discount_id>/edit", methods=["GET", "POST"])
@login_required(["admin"])
def discount_edit(discount_id):
    d = db.session.get(Discount, discount_id) or abort(404)
    if request.method == "POST":
        data, errors = _read_discount_form()
        if errors:
            for e in errors:
                flash(e, "error")
            return _discount_page(d, request.form.to_dict())
        for key, value in data.items():
            setattr(d, key, value)
        db.session.commit()
        flash("Discount updated.", "ok")
        return redirect(url_for("catalog.discounts"))
    f = dict(name=d.name, kind=d.kind, value=d.value, min_purchase=d.min_purchase, min_quantity=d.min_quantity,
             usage_limit=d.usage_limit if d.usage_limit is not None else "",
             start_date=d.start_date.isoformat() if d.start_date else "",
             end_date=d.end_date.isoformat() if d.end_date else "",
             product_id=d.product_id or "")
    return _discount_page(d, f)


@catalog_bp.route("/discounts/<int:discount_id>/delete", methods=["POST"])
@login_required(["admin"])
def discount_delete(discount_id):
    d = db.session.get(Discount, discount_id) or abort(404)
    db.session.delete(d)
    db.session.commit()
    flash("Discount deleted.", "ok")
    return redirect(url_for("catalog.discounts"))
