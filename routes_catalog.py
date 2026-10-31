"""Catalog pages: Taxes (done), then Products, Plans, Discounts.

PATTERN used for every page (copy the Tax code below and rename):
  1. a LIST route      -> shows a table
  2. a NEW route       -> shows a form (GET) and saves it (POST)
  3. an EDIT route     -> same form, filled in
  4. a DELETE route    -> POST only
Only the admin can add / edit / delete. Staff can only look.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from models import db, Tax, SubscriptionLine
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
