from __future__ import annotations

import calendar
import math
import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .categories import category_label
from .models import (
    BalanceSnapshot,
    Category,
    ImportBatch,
    MonthlyReview,
    RecurringSeries,
    Transaction,
)


def month_start(value: date) -> date:
    return value.replace(day=1)


def month_end(value: date) -> date:
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def add_months(value: date, count: int) -> date:
    ordinal = value.year * 12 + value.month - 1 + count
    year, month_zero = divmod(ordinal, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def month_range(value: date) -> tuple[date, date]:
    start = month_start(value)
    return start, month_end(start)


def complete_coverage(db: Session, account_id: str, start: date, end: date) -> bool:
    return (
        db.scalar(
            select(func.count(ImportBatch.id)).where(
                ImportBatch.account_id == account_id,
                ImportBatch.export_from <= start,
                ImportBatch.export_to >= end,
            )
        )
        or 0
    ) > 0


def signed_total(db: Session, account_id: str, start: date, end: date) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.account_id == account_id,
                Transaction.booking_date >= start,
                Transaction.booking_date <= end,
            )
        )
        or 0
    )


def balance_on(db: Session, account_id: str, target: date) -> tuple[int | None, date | None, bool]:
    snapshot = db.scalar(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.balance_date.desc(), BalanceSnapshot.created_at.desc())
        .limit(1)
    )
    if snapshot is None:
        return None, None, False
    if target == snapshot.balance_date:
        return snapshot.balance_cents, snapshot.balance_date, True
    if target < snapshot.balance_date:
        delta = int(
            db.scalar(
                select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                    Transaction.account_id == account_id,
                    Transaction.booking_date > target,
                    Transaction.booking_date <= snapshot.balance_date,
                )
            )
            or 0
        )
        reliable = complete_coverage(db, account_id, target + timedelta(days=1), snapshot.balance_date)
        return snapshot.balance_cents - delta, snapshot.balance_date, reliable
    delta = int(
        db.scalar(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.account_id == account_id,
                Transaction.booking_date > snapshot.balance_date,
                Transaction.booking_date <= target,
            )
        )
        or 0
    )
    reliable = complete_coverage(db, account_id, snapshot.balance_date + timedelta(days=1), target)
    return snapshot.balance_cents + delta, snapshot.balance_date, reliable


def _monthly_total(db: Session, account_id: str, value: date) -> int | None:
    start, end = month_range(value)
    if not complete_coverage(db, account_id, start, end):
        return None
    transactions = db.scalars(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.booking_date >= start,
            Transaction.booking_date <= end,
        )
    ).all()
    categories = {category.id: category for category in db.scalars(select(Category)).all()}
    return sum(
        transaction.amount_cents
        for transaction in transactions
        if not _is_budget_neutral(transaction, categories)
    )


def _root_category(transaction: Transaction, categories: dict[str, Category]) -> Category | None:
    category = categories.get(transaction.category_id) if transaction.category_id else None
    if category is None:
        return None
    return categories.get(category.parent_id) if category.parent_id else category


def _is_budget_neutral(transaction: Transaction, categories: dict[str, Category]) -> bool:
    root = _root_category(transaction, categories)
    return root is not None and root.key == "transfers"


def month_summary(
    db: Session,
    account_id: str,
    value: date,
    locale: str,
    today: date | None = None,
) -> dict:
    start, end = month_range(value)
    current_date = today or date.today()
    is_current_month = start <= current_date <= end
    closing_target = current_date if is_current_month else end
    coverage_end = closing_target if is_current_month else end
    transactions = db.scalars(
        select(Transaction)
        .where(
            Transaction.account_id == account_id,
            Transaction.booking_date >= start,
            Transaction.booking_date <= end,
        )
        .order_by(Transaction.booking_date.desc(), Transaction.id.desc())
    ).all()
    categories = {category.id: category for category in db.scalars(select(Category)).all()}
    budget_transactions = [
        transaction for transaction in transactions if not _is_budget_neutral(transaction, categories)
    ]
    incoming = sum(tx.amount_cents for tx in budget_transactions if tx.amount_cents > 0)
    outgoing = -sum(tx.amount_cents for tx in budget_transactions if tx.amount_cents < 0)
    categorized = sum(abs(tx.amount_cents) for tx in transactions if tx.category_id is not None)
    uncategorized = sum(abs(tx.amount_cents) for tx in transactions if tx.category_id is None)
    contribution_category = db.scalar(select(Category).where(Category.key == "income.household-contribution"))
    household = sum(
        tx.amount_cents
        for tx in transactions
        if contribution_category and tx.category_id == contribution_category.id and tx.amount_cents > 0
    )
    opening, opening_snapshot_date, opening_reliable = balance_on(db, account_id, start - timedelta(days=1))
    closing, closing_snapshot_date, closing_reliable = balance_on(db, account_id, closing_target)
    coverage_complete = complete_coverage(db, account_id, start, coverage_end)
    opening_balance_reliable = opening_reliable and coverage_complete
    closing_balance_reliable = closing_reliable and (is_current_month or coverage_complete)

    expenses: dict[str, int] = defaultdict(int)
    for tx in transactions:
        if tx.amount_cents >= 0 or _is_budget_neutral(tx, categories):
            continue
        if tx.category_id and tx.category_id in categories:
            category = categories[tx.category_id]
            root = categories.get(category.parent_id) if category.parent_id else category
            key = root.id if root else category.id
        else:
            key = "__uncategorized__"
        expenses[key] += -tx.amount_cents
    breakdown = []
    for key, amount in sorted(expenses.items(), key=lambda item: item[1], reverse=True):
        category = categories.get(key)
        breakdown.append(
            {
                "category_id": None if key == "__uncategorized__" else key,
                "key": None if category is None else category.key,
                "label": None if category is None else category_label(category, locale),
                "amount_cents": amount,
            }
        )
    previous = _monthly_total(db, account_id, add_months(start, -1))
    previous_year = _monthly_total(db, account_id, add_months(start, -12))
    review = db.scalar(
        select(MonthlyReview)
        .where(MonthlyReview.account_id == account_id, MonthlyReview.month == start)
        .order_by(MonthlyReview.revision.desc())
        .limit(1)
    )
    return {
        "month": start,
        "opening_balance_cents": opening,
        "closing_balance_cents": closing,
        "balance_effective_date": (
            closing_target if closing_balance_reliable else closing_snapshot_date or opening_snapshot_date
        ),
        "balance_reliable": closing_balance_reliable,
        "opening_balance_reliable": opening_balance_reliable,
        "closing_balance_reliable": closing_balance_reliable,
        "coverage_complete": coverage_complete,
        "incoming_cents": incoming,
        "outgoing_cents": outgoing,
        "net_cents": incoming - outgoing,
        "household_contribution_cents": household,
        "categorized_cents": categorized,
        "uncategorized_cents": uncategorized,
        "uncategorized_count": sum(tx.category_id is None for tx in transactions),
        "transaction_count": len(transactions),
        "breakdown": breakdown,
        "previous_month_net_cents": previous,
        "previous_year_net_cents": previous_year,
        "recent_transactions": transactions[:7],
        "review": review,
    }


def least_squares(values: list[float]) -> tuple[float, float, list[float]]:
    if not values:
        return 0.0, 0.0, []
    if len(values) < 3:
        mean = statistics.fmean(values)
        return mean, 0.0, [value - mean for value in values]
    xs = list(range(len(values)))
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(values)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values, strict=True)) / denominator
    intercept = y_mean - slope * x_mean
    residuals = [value - (intercept + slope * x) for x, value in zip(xs, values, strict=True)]
    return intercept, slope, residuals


def category_trend(
    db: Session, account_id: str, category_id: str, locale: str, today: date | None = None
) -> dict:
    category = db.get(Category, category_id)
    now = today or date.today()
    current = month_start(now)
    points = []
    values: list[float] = []
    for offset in range(-12, 0):
        month = add_months(current, offset)
        start, end = month_range(month)
        complete = complete_coverage(db, account_id, start, end)
        total = int(
            db.scalar(
                select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                    Transaction.account_id == account_id,
                    Transaction.category_id == category_id,
                    Transaction.booking_date >= start,
                    Transaction.booking_date <= end,
                )
            )
            or 0
        )
        if complete:
            values.append(float(total))
        points.append({"month": month, "amount_cents": total, "complete": complete})
    complete_points = [point for point in points if point["complete"]]
    complete_values = [float(point["amount_cents"]) for point in complete_points]
    intercept, slope, _ = least_squares(complete_values[-12:])
    moving = []
    for index, point in enumerate(complete_points):
        subset = complete_points[max(0, index - 2) : index + 1]
        moving.append(
            {
                "month": point["month"],
                "amount_cents": round(statistics.fmean(item["amount_cents"] for item in subset))
                if len(subset) == 3
                else None,
            }
        )
    return {
        "category_id": category_id,
        "category_label": category_label(category, locale),
        "points": points,
        "moving_average": moving,
        "linear_monthly_change_cents": round(slope) if len(complete_values) >= 3 else None,
        "sparse": len(complete_values) < 3,
    }


def _project_cadence_dates(series: RecurringSeries, start: date, end: date) -> Iterable[date]:
    current = series.expected_next_date
    guard = 0
    while current < start and guard < 1000:
        if series.cadence == "weekly":
            current += timedelta(days=7)
        elif series.cadence == "monthly":
            current = add_months(current, 1)
        elif series.cadence == "quarterly":
            current = add_months(current, 3)
        else:
            current = add_months(current, 12)
        guard += 1
    while current <= end and guard < 1000:
        yield current
        if series.cadence == "weekly":
            current += timedelta(days=7)
        elif series.cadence == "monthly":
            current = add_months(current, 1)
        elif series.cadence == "quarterly":
            current = add_months(current, 3)
        else:
            current = add_months(current, 12)
        guard += 1


def balance_forecast(db: Session, account_id: str, today: date | None = None) -> dict:
    now = today or date.today()
    snapshot = db.scalar(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.balance_date.desc(), BalanceSnapshot.created_at.desc())
        .limit(1)
    )
    if snapshot is None:
        return {"available": False, "reason": "missing_balance", "points": [], "recurring": []}
    current_month = month_start(now)
    history_months = [add_months(current_month, offset) for offset in range(-12, 0)]
    complete_months = [
        month
        for month in history_months
        if complete_coverage(db, account_id, month_start(month), month_end(month))
    ]
    if not complete_months:
        return {"available": False, "reason": "missing_history", "points": [], "recurring": []}

    recurring = db.scalars(
        select(RecurringSeries).where(
            RecurringSeries.account_id == account_id,
            RecurringSeries.status == "confirmed",
            RecurringSeries.enabled.is_(True),
        )
    ).all()
    recurring_transaction_ids = set()
    for series in recurring:
        recurring_transaction_ids.update(series.evidence.get("transaction_ids", []))

    monthly_residual_totals: dict[date, int] = {}
    for month in complete_months:
        start, end = month_range(month)
        query = select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.account_id == account_id,
            Transaction.booking_date >= start,
            Transaction.booking_date <= end,
        )
        if recurring_transaction_ids:
            query = query.where(Transaction.id.not_in(recurring_transaction_ids))
        monthly_residual_totals[month] = int(db.scalar(query) or 0)

    start_date = snapshot.balance_date + timedelta(days=1)
    final_month = date(snapshot.balance_date.year, 12, 1)
    final_date = month_end(final_month)
    recurring_entries = []
    recurring_by_month: dict[date, int] = defaultdict(int)
    for series in recurring:
        for expected in _project_cadence_dates(series, start_date, final_date):
            month = month_start(expected)
            recurring_by_month[month] += series.typical_amount_cents
            recurring_entries.append(
                {
                    "series_id": series.id,
                    "date": expected,
                    "amount_cents": series.typical_amount_cents,
                    "cadence": series.cadence,
                    "counterparty": series.normalized_counterparty,
                }
            )

    total_history = list(monthly_residual_totals.values())[-6:]
    variable_monthly_cashflow = round(statistics.median(total_history))
    total_residuals = [float(value - variable_monthly_cashflow) for value in total_history]
    residual_std = statistics.pstdev(total_residuals) if len(total_residuals) >= 2 else 0.0
    balance = snapshot.balance_cents
    points = [
        {
            "month": month_start(snapshot.balance_date),
            "balance_cents": balance,
            "low_cents": balance,
            "high_cents": balance,
            "variable_cashflow_cents": 0,
            "recurring_cashflow_cents": 0,
        }
    ]
    months_remaining = 12 - snapshot.balance_date.month
    for horizon in range(1, months_remaining + 1):
        target_month = add_months(month_start(snapshot.balance_date), horizon)
        variable = variable_monthly_cashflow
        recurring_amount = recurring_by_month.get(target_month, 0)
        balance += variable + recurring_amount
        uncertainty = round(residual_std * math.sqrt(horizon))
        points.append(
            {
                "month": target_month,
                "balance_cents": balance,
                "low_cents": balance - uncertainty,
                "high_cents": balance + uncertainty,
                "variable_cashflow_cents": variable,
                "recurring_cashflow_cents": recurring_amount,
            }
        )
    return {
        "available": True,
        "reason": None,
        "snapshot_date": snapshot.balance_date,
        "snapshot_balance_cents": snapshot.balance_cents,
        "history_month_count": len(complete_months),
        "points": points,
        "recurring": recurring_entries,
        "method": "median-monthly-net-with-confirmed-recurring-separation",
    }
