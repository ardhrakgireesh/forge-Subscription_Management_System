"""Billing engine: turns Active subscriptions into invoices.

Used by the "Run Billing" button (routes_invoices.py).
The rule "nothing is billed twice" is protected two ways:
  1. we look for an existing invoice for the same subscription + period first,
  2. the database itself refuses a second one (unique constraint uq_sub_period).
"""
import calendar
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from models import db, Subscription, SubscriptionLine, Invoice, InvoiceLine, Discount, ProductVariant

TERMS_DAYS = {"Immediate": 0, "15 days": 15, "30 days": 30, "45 days": 45}
MAX_PERIODS_PER_RUN = 12     # safety: never create more than 12 invoices for one subscription in one click


def add_period(d, period):
    """Moves a date forward by one billing period (daily / weekly / monthly / yearly)."""
    if period == "daily":
        return d + timedelta(days=1)
    if period == "weekly":
        return d + timedelta(days=7)
    if period == "monthly":
        year, month = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
        return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))
    if period == "yearly":
        year = d.year + 1
        return date(year, d.month, min(d.day, calendar.monthrange(year, d.month)[1]))
    raise ValueError(f"Unknown billing period: {period}")


def discount_is_valid(d, today):
    """A discount works only between its dates and until its usage limit is reached."""
    if d.start_date and today < d.start_date:
        return False
    if d.end_date and today > d.end_date:
        return False
    if d.usage_limit is not None and (d.times_used or 0) >= d.usage_limit:
        return False
    return True


def build_invoice(sub, period_start, today, discounts, variants):
    """Creates (but does not save) one invoice for one period of one subscription.
    Returns (invoice, list_of_discounts_used)."""
    period_end = add_period(period_start, sub.plan.billing_period) - timedelta(days=1)
    lines = list(sub.lines)

    # 1. amount of every line before discount
    net = {l.id: round(l.quantity * l.unit_price, 2) for l in lines}
    taken = {l.id: 0.0 for l in lines}          # discount money given to each line so far

    # 2. discounts: each one works on whole subscription or on one product
    used = []
    for d in discounts:
        if not discount_is_valid(d, today):
            continue
        targets = [l for l in lines if d.product_id is None or l.product_id == d.product_id]
        base = sum(net[l.id] - taken[l.id] for l in targets)
        qty = sum(l.quantity for l in targets)
        if not targets or base <= 0:
            continue
        if base < (d.min_purchase or 0) or qty < (d.min_quantity or 0):
            continue
        amount = base * d.value / 100 if d.kind == "percent" else d.value
        amount = round(min(amount, base), 2)
        if amount <= 0:
            continue
        left_to_share = amount
        for i, l in enumerate(targets):         # share it between the lines, in proportion
            room = net[l.id] - taken[l.id]
            share = left_to_share if i == len(targets) - 1 else round(amount * room / base, 2)
            share = max(0.0, min(share, room))
            taken[l.id] += share
            left_to_share -= share
        used.append((d, amount))

    # 3. build invoice lines; tax is charged on the amount AFTER discount
    inv = Invoice(subscription_id=sub.id, customer_id=sub.customer_id, period_start=period_start,
                  due_date=period_start + timedelta(days=TERMS_DAYS.get(sub.payment_terms, 0)),
                  status="Draft")
    subtotal = tax_total = discount_total = 0.0
    for l in lines:
        tax = round((net[l.id] - taken[l.id]) * l.tax.rate / 100, 2) if l.tax else 0.0
        name = l.product.name
        v = variants.get(l.variant_id)
        if v:
            name += f" ({v.attribute}: {v.value})"
        inv.lines.append(InvoiceLine(
            description=f"{name} · {period_start:%d %b %Y} to {period_end:%d %b %Y}",
            quantity=l.quantity, unit_price=l.unit_price, tax_amount=tax, amount=net[l.id]))
        subtotal += net[l.id]
        tax_total += tax
    for d, amount in used:
        inv.lines.append(InvoiceLine(description=f"Discount: {d.name}", quantity=1,
                                     unit_price=-amount, tax_amount=0.0, amount=-amount))
        discount_total += amount

    inv.subtotal = round(subtotal, 2)
    inv.discount_total = round(discount_total, 2)
    inv.tax_total = round(tax_total, 2)
    inv.total = round(inv.subtotal - inv.discount_total + inv.tax_total, 2)
    return inv, [d for d, _ in used]


def run_billing(today=None):
    """Creates invoices for every Active subscription that is due. Returns a dict of counts."""
    today = today or date.today()
    stats = {"created": 0, "duplicates": 0, "closed": 0, "not_due": 0, "no_lines": 0}

    variants = {v.id: v for v in ProductVariant.query.all()}
    discounts = Discount.query.order_by(Discount.id).all()
    existing = {(sid, ps) for sid, ps in db.session.query(Invoice.subscription_id, Invoice.period_start)}

    subs = (Subscription.query
            .options(joinedload(Subscription.plan),
                     selectinload(Subscription.lines).joinedload(SubscriptionLine.tax),
                     selectinload(Subscription.lines).joinedload(SubscriptionLine.product))
            .filter(Subscription.status == "Active").all())

    for sub in subs:
        plan = sub.plan
        # Plans that close on their own once they end
        if plan.auto_close and plan.end_date and plan.end_date < today:
            sub.status, sub.next_invoice_date = "Closed", None
            stats["closed"] += 1
            continue
        if not sub.next_invoice_date or sub.next_invoice_date > today:
            stats["not_due"] += 1
            continue
        if not sub.lines:
            stats["no_lines"] += 1
            continue

        made = 0
        while sub.next_invoice_date and sub.next_invoice_date <= today and made < MAX_PERIODS_PER_RUN:
            period_start = sub.next_invoice_date
            if sub.expiry_date and period_start > sub.expiry_date:
                sub.next_invoice_date = None        # contract ended, nothing more to bill
                break
            if (sub.id, period_start) in existing:
                stats["duplicates"] += 1            # already billed: skip, never twice
            else:
                try:
                    with db.session.begin_nested():
                        inv, used = build_invoice(sub, period_start, today, discounts, variants)
                        db.session.add(inv)
                        db.session.flush()
                        inv.number = f"INV{inv.id:04d}"
                except IntegrityError:               # the database said "this period is already billed"
                    stats["duplicates"] += 1
                else:
                    for d in used:
                        d.times_used = (d.times_used or 0) + 1
                    existing.add((sub.id, period_start))
                    stats["created"] += 1
            sub.next_invoice_date = add_period(period_start, plan.billing_period)
            made += 1

    db.session.commit()
    return stats
