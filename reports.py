"""Numbers for the finance dashboard (MRR, collected, outstanding, overdue, revenue at risk).

All the maths lives here so dashboard.html only has to show the results.
Everything is computed with a few grouped database queries, so it stays fast with thousands of rows.
"""
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from models import db, Subscription, SubscriptionLine, Plan, Invoice, Payment

# How many billing periods fit in one month (used to turn any plan into "per month").
PERIODS_PER_MONTH = {"daily": 365 / 12, "weekly": 52 / 12, "monthly": 1, "yearly": 1 / 12}

RANGES = [("month", "This month"), ("90", "Last 90 days"), ("year", "This year"), ("all", "All time")]


def month_start(d, back):
    """First day of the month, `back` months before d."""
    year, month = d.year, d.month - back
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def monthly_recurring_revenue():
    """Every Active subscription, turned into a per-month amount (before tax)."""
    rows = (db.session.query(Plan.billing_period,
                             func.sum(SubscriptionLine.quantity * SubscriptionLine.unit_price))
            .select_from(Subscription)
            .join(Plan, Subscription.plan_id == Plan.id)
            .join(SubscriptionLine, SubscriptionLine.subscription_id == Subscription.id)
            .filter(Subscription.status == "Active")
            .group_by(Plan.billing_period).all())
    return round(sum((amount or 0) * PERIODS_PER_MONTH.get(period, 0) for period, amount in rows), 2)


def open_invoices():
    """Confirmed (unpaid or part-paid) invoices as a list of (invoice, paid_so_far)."""
    paid = func.coalesce(func.sum(Payment.amount), 0)
    return (db.session.query(Invoice, paid)
            .outerjoin(Payment, Payment.invoice_id == Invoice.id)
            .filter(Invoice.status == "Confirmed")
            .group_by(Invoice.id).all())


def dashboard_data(range_key="month", today=None):
    today = today or date.today()
    if range_key not in dict(RANGES):
        range_key = "month"

    # ---- revenue collected (payments), filtered by the chosen range ----
    since = {"month": today.replace(day=1), "90": today - timedelta(days=90),
             "year": date(today.year, 1, 1), "all": None}[range_key]
    q = db.session.query(func.coalesce(func.sum(Payment.amount), 0))
    if since:
        q = q.filter(Payment.paid_on >= since)
    collected = round(q.scalar() or 0, 2)

    # ---- outstanding and overdue invoices ----
    outstanding = overdue_amount = 0.0
    overdue = []
    for inv, paid in open_invoices():
        balance = max(round(inv.total - paid, 2), 0.0)
        outstanding += balance
        if inv.due_date and inv.due_date < today:
            overdue_amount += balance
            overdue.append({"inv": inv, "balance": balance, "days_late": (today - inv.due_date).days})
    overdue.sort(key=lambda r: r["days_late"], reverse=True)       # most late first
    overdue_count = len(overdue)
    top_overdue = overdue[:8]
    for r in top_overdue:                                          # load names only for the rows we show
        r["customer"] = r["inv"].customer.name

    # ---- subscriptions expiring within 7 days ----
    expiring = (Subscription.query
                .options(joinedload(Subscription.customer), joinedload(Subscription.plan),
                         selectinload(Subscription.lines))
                .filter(Subscription.status == "Active",
                        Subscription.expiry_date >= today,
                        Subscription.expiry_date <= today + timedelta(days=7))
                .order_by(Subscription.expiry_date).all())
    expiring_rows = []
    expiring_value = 0.0
    for s in expiring:
        value = round(sum(l.quantity * l.unit_price for l in s.lines), 2)
        expiring_value += value
        expiring_rows.append({"sub": s, "value": value, "days_left": (s.expiry_date - today).days})

    # ---- revenue chart: payments of the last 6 months ----
    months = [month_start(today, i) for i in range(5, -1, -1)]
    ym = func.strftime("%Y-%m", Payment.paid_on).label("ym")
    by_month = dict(db.session.query(ym, func.sum(Payment.amount))
                    .filter(Payment.paid_on >= months[0]).group_by(ym).all())
    values = [round(by_month.get(f"{m:%Y-%m}", 0) or 0, 2) for m in months]
    top = max(values) or 1
    bars = [{"label": f"{m:%b}", "value": v, "pct": max(round(v * 100 / top), 3) if v else 0}
            for m, v in zip(months, values)]

    # ---- small summaries ----
    sub_counts = dict(db.session.query(Subscription.status, func.count(Subscription.id))
                      .group_by(Subscription.status).all())
    inv_counts = dict(db.session.query(Invoice.status, func.count(Invoice.id))
                      .group_by(Invoice.status).all())

    return {
        "range_key": range_key, "ranges": RANGES,
        "mrr": monthly_recurring_revenue(),
        "active": sub_counts.get("Active", 0),
        "collected": collected,
        "outstanding": round(outstanding, 2),
        "overdue_count": overdue_count, "overdue_amount": round(overdue_amount, 2),
        "overdue_rows": top_overdue,
        "expiring_rows": expiring_rows, "expiring_value": round(expiring_value, 2),
        "at_risk": round(overdue_amount + expiring_value, 2),
        "bars": bars, "sub_counts": sub_counts, "inv_counts": inv_counts,
        "subs_total": sum(sub_counts.values()), "invs_total": sum(inv_counts.values()),
    }
