"""Strict order-record normalization, used to exercise the regression gate."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN


def normalize_order(record: dict) -> dict:
    if not isinstance(record, dict) or set(record) != {"order_id", "date", "amount", "currency"}:
        raise ValueError("order requires order_id, date, amount, currency only")
    identifier = record["order_id"]
    if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 256:
        raise ValueError("invalid order id")
    raw_date = record["date"]
    if not isinstance(raw_date, str) or len(raw_date) != 10:
        raise ValueError("date must be YYYY-MM-DD")
    parsed_date = date.fromisoformat(raw_date)
    if parsed_date.isoformat() != raw_date:
        raise ValueError("date must be canonical YYYY-MM-DD")
    raw_amount = record["amount"]
    if not isinstance(raw_amount, str) or len(raw_amount) > 64 or raw_amount != raw_amount.strip():
        raise ValueError("amount must be a bounded decimal string")
    try:
        amount = Decimal(raw_amount)
        if not amount.is_finite() or abs(amount) >= Decimal("1000000000000"):
            raise ValueError("amount out of range")
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise ValueError("invalid amount") from exc
    currency = record["currency"]
    if not isinstance(currency, str) or currency.upper() not in {"USD", "EUR", "GBP"}:
        raise ValueError("unsupported currency")
    return {"order_id": identifier.strip(), "date": parsed_date.isoformat(),
            "amount": format(rounded, ".2f"), "currency": currency.upper()}
