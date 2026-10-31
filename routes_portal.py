"""Customer portal: a customer sees ONLY their own subscriptions and invoices.

Every query below filters by customer_id = the logged-in user, so a customer can never
open someone else's record (even by typing another id in the URL: they get a 404).
"""
from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, abort
from sqlalchemy.orm import joinedload

from models import db, Subscription, Invoice, ProductVariant
from helpers import login_required, current_user
from routes_subscriptions import subscription_totals, line_totals

portal_bp = Blueprint("portal", __name__)


def _my_subscription(sub_id):
    """The subscription, but only if it belongs to the logged-in customer (and is not an internal draft)."""
    sub = db.session.get(Subscription, sub_id)
    if not sub or sub.customer_id != current_user().id or sub.status == "Draft":
        abort(404)
    return sub


@portal_bp.route("/portal/subscriptions")
@login_required(["customer"])
def my_subscriptions():
    rows = (Subscription.query.options(joinedload(Subscription.plan))
            .filter(Subscription.customer_id == current_user().id, Subscription.status != "Draft")
            .order_by(Subscription.id.desc()).all())
    return render_template("portal_subscriptions.html", rows=rows)


@portal_bp.route("/portal/subscriptions/<int:sub_id>")
@login_required(["customer"])
def my_subscription_view(sub_id):
    sub = _my_subscription(sub_id)
    variants = {v.id: v for v in ProductVariant.query.all()}
    can_close = (sub.status == "Active" and sub.plan.closable)
    return render_template("portal_subscription_view.html", s=sub, variants=variants,
                           totals=subscription_totals(sub), line_totals=line_totals, can_close=can_close)


@portal_bp.route("/portal/subscriptions/<int:sub_id>/close", methods=["POST"])
@login_required(["customer"])
def my_subscription_close(sub_id):
    sub = _my_subscription(sub_id)
    if sub.status != "Active":
        flash("Only an active subscription can be closed.", "error")
    elif not sub.plan.closable:
        flash("This plan cannot be closed early. Please contact Brightloop.", "error")
    else:
        sub.status, sub.next_invoice_date = "Closed", None
        db.session.commit()
        flash(f"{sub.number} has been closed.", "ok")
    return redirect(url_for("portal.my_subscription_view", sub_id=sub.id))


@portal_bp.route("/portal/invoices")
@login_required(["customer"])
def my_invoices():
    # Customers never see drafts or cancelled invoices.
    rows = (Invoice.query.options(joinedload(Invoice.subscription))
            .filter(Invoice.customer_id == current_user().id, Invoice.status.in_(["Confirmed", "Paid"]))
            .order_by(Invoice.id.desc()).all())
    today = date.today()
    overdue = {i.id for i in rows if i.status == "Confirmed" and i.due_date and i.due_date < today}
    owed = round(sum(i.total - sum(p.amount for p in i.payments) for i in rows if i.status == "Confirmed"), 2)
    return render_template("portal_invoices.html", rows=rows, overdue=overdue, owed=max(owed, 0))


@portal_bp.route("/portal/invoices/<int:inv_id>")
@login_required(["customer"])
def my_invoice_view(inv_id):
    inv = db.session.get(Invoice, inv_id)
    if not inv or inv.customer_id != current_user().id or inv.status not in ("Confirmed", "Paid"):
        abort(404)
    paid = round(sum(p.amount for p in inv.payments), 2)
    overdue = inv.status == "Confirmed" and inv.due_date is not None and inv.due_date < date.today()
    return render_template("portal_invoice_view.html", inv=inv, paid=paid,
                           balance=max(round(inv.total - paid, 2), 0), overdue=overdue)
