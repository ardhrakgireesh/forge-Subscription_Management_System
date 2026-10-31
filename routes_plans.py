"""Plans: what a subscription costs and how often it bills.

Only the admin can add / edit / delete plans. Staff can only look.
"""
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from models import db, Plan, Subscription
from helpers import login_required

plans_bp = Blueprint("plans", __name__)

PERIODS = ["daily", "weekly", "monthly", "yearly"]


def _parse_date(text):
    """'2026-11-30' -> date. Empty text -> None. Bad text raises ValueError."""
    text = (text or "").strip()
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def _form_values():
    """The raw form as a simple dict, used to refill the form after an error."""
    f = request.form.to_dict()
    for box in ("auto_close", "closable", "pausable", "renewable"):
        f[box] = box in request.form          # checkboxes are only sent when ticked
    return f


def _plan_values(plan):
    """A saved plan as a dict for the form (used by the Edit page)."""
    return {
        "name": plan.name, "price": plan.price, "billing_period": plan.billing_period,
        "min_quantity": plan.min_quantity,
        "start_date": plan.start_date.isoformat() if plan.start_date else "",
        "end_date": plan.end_date.isoformat() if plan.end_date else "",
        "auto_close": plan.auto_close, "closable": plan.closable,
        "pausable": plan.pausable, "renewable": plan.renewable,
    }


def _read_plan_form(plan_id=None):
    """Checks every field. Returns (clean_data, errors)."""
    f = request.form
    errors = []

    name = f.get("name", "").strip()
    if not name:
        errors.append("Plan name is required.")
    elif len(name) > 100:
        errors.append("Plan name must be 100 characters or less.")
    else:
        same = Plan.query.filter(db.func.lower(Plan.name) == name.lower())
        if plan_id:
            same = same.filter(Plan.id != plan_id)
        if same.first():
            errors.append("A plan with this name already exists.")

    price = None
    try:
        price = float(f.get("price", "").strip())
        if price < 0:
            errors.append("Price cannot be negative.")
    except ValueError:
        errors.append("Price must be a number, like 499.")

    period = f.get("billing_period", "")
    if period not in PERIODS:
        errors.append("Choose how often the plan bills.")

    min_qty = None
    try:
        min_qty = int(f.get("min_quantity", "").strip())
        if min_qty < 1:
            errors.append("Minimum quantity must be at least 1.")
    except ValueError:
        errors.append("Minimum quantity must be a whole number.")

    start = end = None
    try:
        start = _parse_date(f.get("start_date"))
        end = _parse_date(f.get("end_date"))
        if start and end and end < start:
            errors.append("End date cannot be before the start date.")
    except ValueError:
        errors.append("Enter valid dates.")

    auto_close = "auto_close" in f
    if auto_close and not end:
        errors.append("Set an end date if the plan should close on its own.")

    data = dict(name=name, price=price, billing_period=period, min_quantity=min_qty,
                start_date=start, end_date=end, auto_close=auto_close,
                closable="closable" in f, pausable="pausable" in f,
                renewable="renewable" in f)
    return data, errors


@plans_bp.route("/plans")
@login_required(["admin", "staff"])
def plans():
    return render_template("plans.html", plans=Plan.query.order_by(Plan.name).all())


@plans_bp.route("/plans/new", methods=["GET", "POST"])
@login_required(["admin"])
def plan_new():
    if request.method == "POST":
        data, errors = _read_plan_form()
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("plan_form.html", plan=None, f=_form_values(), periods=PERIODS)
        db.session.add(Plan(**data))
        db.session.commit()
        flash("Plan added.", "ok")
        return redirect(url_for("plans.plans"))
    defaults = {"min_quantity": 1, "closable": True, "pausable": True, "renewable": True}
    return render_template("plan_form.html", plan=None, f=defaults, periods=PERIODS)


@plans_bp.route("/plans/<int:plan_id>/edit", methods=["GET", "POST"])
@login_required(["admin"])
def plan_edit(plan_id):
    plan = db.session.get(Plan, plan_id) or abort(404)
    if request.method == "POST":
        data, errors = _read_plan_form(plan_id)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("plan_form.html", plan=plan, f=_form_values(), periods=PERIODS)
        for key, value in data.items():
            setattr(plan, key, value)
        db.session.commit()
        flash("Plan updated.", "ok")
        return redirect(url_for("plans.plans"))
    return render_template("plan_form.html", plan=plan, f=_plan_values(plan), periods=PERIODS)


@plans_bp.route("/plans/<int:plan_id>/delete", methods=["POST"])
@login_required(["admin"])
def plan_delete(plan_id):
    plan = db.session.get(Plan, plan_id) or abort(404)
    if Subscription.query.filter_by(plan_id=plan.id).first():
        flash("This plan is used by a subscription, so it cannot be deleted.", "error")
    else:
        db.session.delete(plan)
        db.session.commit()
        flash("Plan deleted.", "ok")
    return redirect(url_for("plans.plans"))
