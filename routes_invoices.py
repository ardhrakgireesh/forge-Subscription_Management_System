"""Invoices: list, Run Billing, view, confirm, cancel, send, print.

Status flow: Draft -> Confirmed -> Paid  (a Draft or Confirmed invoice can also be Cancelled).
"Paid" is set automatically when payments cover the total (the Payments page does that).
"""
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from sqlalchemy.orm import joinedload

from models import db, Invoice
from helpers import login_required
from billing import run_billing

invoices_bp = Blueprint("invoices", __name__)

INV_STATUSES = ["Draft", "Confirmed", "Paid", "Cancelled"]


def _is_overdue(inv, today=None):
    """Confirmed (unpaid) and past its due date."""
    today = today or date.today()
    return inv.status == "Confirmed" and inv.due_date is not None and inv.due_date < today


@invoices_bp.route("/invoices")
@login_required(["admin", "staff"])
def invoices():
    status = request.args.get("status", "")
    query = Invoice.query.options(joinedload(Invoice.customer), joinedload(Invoice.subscription))
    if status == "Overdue":
        query = query.filter(Invoice.status == "Confirmed", Invoice.due_date < date.today())
    elif status in INV_STATUSES:
        query = query.filter(Invoice.status == status)
    rows = query.order_by(Invoice.id.desc()).all()
    today = date.today()
    return render_template("invoices.html", rows=rows, statuses=INV_STATUSES + ["Overdue"], status=status,
                           overdue={r.id for r in rows if _is_overdue(r, today)})


@invoices_bp.route("/invoices/run", methods=["POST"])
@login_required(["admin", "staff"])
def invoices_run():
    s = run_billing()
    msg = f"{s['created']} created, {s['duplicates']} duplicates skipped"
    extra = []
    if s["not_due"]:
        extra.append(f"{s['not_due']} not due yet")
    if s["closed"]:
        extra.append(f"{s['closed']} closed automatically")
    if s["no_lines"]:
        extra.append(f"{s['no_lines']} skipped (no lines)")
    if extra:
        msg += " (" + ", ".join(extra) + ")"
    flash("Billing finished: " + msg + ".", "ok")
    return redirect(url_for("invoices.invoices"))


@invoices_bp.route("/invoices/confirm-all", methods=["POST"])
@login_required(["admin", "staff"])
def invoices_confirm_all():
    n = Invoice.query.filter_by(status="Draft").update({"status": "Confirmed"})
    db.session.commit()
    flash(f"{n} draft invoice(s) confirmed.", "ok")
    return redirect(url_for("invoices.invoices"))


@invoices_bp.route("/invoices/<int:inv_id>")
@login_required(["admin", "staff"])
def invoice_view(inv_id):
    inv = db.session.get(Invoice, inv_id) or abort(404)
    paid = round(sum(p.amount for p in inv.payments), 2)
    return render_template("invoice_view.html", inv=inv, paid=paid, balance=round(inv.total - paid, 2),
                           overdue=_is_overdue(inv))


def _change(inv_id, allowed_from, new_status, ok_message, bad_message):
    inv = db.session.get(Invoice, inv_id) or abort(404)
    if inv.status not in allowed_from:
        flash(bad_message, "error")
    else:
        inv.status = new_status
        db.session.commit()
        flash(ok_message, "ok")
    return redirect(url_for("invoices.invoice_view", inv_id=inv.id))


@invoices_bp.route("/invoices/<int:inv_id>/confirm", methods=["POST"])
@login_required(["admin", "staff"])
def invoice_confirm(inv_id):
    return _change(inv_id, ["Draft"], "Confirmed", "Invoice confirmed.", "Only a draft invoice can be confirmed.")


@invoices_bp.route("/invoices/<int:inv_id>/cancel", methods=["POST"])
@login_required(["admin", "staff"])
def invoice_cancel(inv_id):
    inv = db.session.get(Invoice, inv_id) or abort(404)
    if inv.payments:
        flash("This invoice has payments, so it cannot be cancelled.", "error")
        return redirect(url_for("invoices.invoice_view", inv_id=inv.id))
    return _change(inv_id, ["Draft", "Confirmed"], "Cancelled", "Invoice cancelled.",
                   "Only a draft or confirmed invoice can be cancelled.")


@invoices_bp.route("/invoices/<int:inv_id>/send", methods=["POST"])
@login_required(["admin", "staff"])
def invoice_send(inv_id):
    inv = db.session.get(Invoice, inv_id) or abort(404)
    if inv.status not in ("Confirmed", "Paid"):
        flash("Confirm the invoice before sending it.", "error")
    else:
        # TODO: real email (smtplib). For the demo we print it, like the password reset link.
        print(f"EMAIL: invoice {inv.number} sent to {inv.customer.email}")
        flash(f"Invoice {inv.number} sent to {inv.customer.email}.", "ok")
    return redirect(url_for("invoices.invoice_view", inv_id=inv.id))
