"""Payments: record money received against an invoice, and chase overdue invoices.

When the payments of an invoice add up to its total, the invoice becomes Paid.
Admin and staff can use this page. Customers cannot.
"""
import math
from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from models import db, Invoice, Payment
from helpers import login_required
from reports import open_invoices      # Confirmed invoices with how much was paid so far

payments_bp = Blueprint("payments", __name__)

METHODS = ["Cash", "UPI", "Card", "Bank"]


def _open_list():
    """Invoices that can still receive money: [(invoice, paid_so_far, balance)], oldest first."""
    rows = []
    for inv, paid in open_invoices():
        balance = round(inv.total - paid, 2)
        if balance > 0:
            rows.append((inv, paid, balance))
    rows.sort(key=lambda r: (r[0].due_date or date.max, r[0].id))
    return rows


@payments_bp.route("/payments")
@login_required(["admin", "staff"])
def payments():
    today = date.today()
    overdue = []
    for inv, paid, balance in _open_list():
        if inv.due_date and inv.due_date < today:
            overdue.append({"inv": inv, "balance": balance, "days_late": (today - inv.due_date).days,
                            "customer": inv.customer.name})
    rows = (Payment.query
            .options(joinedload(Payment.invoice).joinedload(Invoice.customer))
            .order_by(Payment.paid_on.desc(), Payment.id.desc()).limit(300).all())
    return render_template("payments.html", overdue=overdue, rows=rows)


@payments_bp.route("/payments/new", methods=["GET", "POST"])
@login_required(["admin", "staff"])
def payment_new():
    open_rows = _open_list()
    balances = {inv.id: balance for inv, _paid, balance in open_rows}

    if request.method == "POST":
        f = request.form
        errors = []

        # Invoice: must be one of the Confirmed, not fully paid invoices.
        try:
            invoice_id = int(f.get("invoice_id", ""))
        except ValueError:
            invoice_id = 0
        if invoice_id not in balances:
            errors.append("Choose an invoice that is confirmed and not fully paid.")

        method = f.get("method", "")
        if method not in METHODS:                         # never trust the browser
            errors.append("Choose a payment method.")

        amount = None
        try:
            amount = round(float(f.get("amount", "").strip()), 2)
            if not math.isfinite(amount) or amount <= 0:
                errors.append("Amount must be above 0.")
            elif invoice_id in balances and amount > balances[invoice_id] + 0.005:
                errors.append(f"Amount cannot be more than the balance of ₹{balances[invoice_id]:.2f}.")
        except ValueError:
            errors.append("Amount must be a number, like 500.")

        paid_on = None
        try:
            paid_on = datetime.strptime(f.get("paid_on", "").strip(), "%Y-%m-%d").date()
            if paid_on > date.today():
                errors.append("Payment date cannot be in the future.")
        except ValueError:
            errors.append("Enter a valid payment date.")

        note = f.get("note", "").strip()
        if len(note) > 200:
            errors.append("Note must be 200 characters or less.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("payment_form.html", open_rows=open_rows, methods=METHODS, f=f.to_dict(),
                                   today=date.today().isoformat())

        invoice = db.session.get(Invoice, invoice_id)
        db.session.add(Payment(invoice_id=invoice.id, method=method, amount=amount, paid_on=paid_on, note=note))
        db.session.flush()
        # Add up every payment of this invoice. Enough money -> the invoice is Paid.
        total_paid = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
            Payment.invoice_id == invoice.id).scalar()
        if total_paid >= invoice.total - 0.005:
            invoice.status = "Paid"
            flash(f"Payment saved. Invoice {invoice.number} is now Paid.", "ok")
        else:
            flash(f"Payment saved. ₹{invoice.total - total_paid:.2f} is still owed on {invoice.number}.", "ok")
        db.session.commit()
        return redirect(url_for("payments.payments"))

    pre = request.args.get("invoice", "")
    return render_template("payment_form.html", open_rows=open_rows, methods=METHODS,
                           f={"invoice_id": pre, "paid_on": date.today().isoformat()},
                           today=date.today().isoformat())
