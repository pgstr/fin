from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from .errors import ValidationError

HEADERS = [
    "Buchungsdatum",
    "Wertstellung",
    "Status",
    "Zahlungspflichtige*r",
    "Zahlungsempfänger*in",
    "Verwendungszweck",
    "Umsatztyp",
    "IBAN",
    "Betrag (€)",
    "Gläubiger-ID",
    "Mandatsreferenz",
    "Kundenreferenz",
]
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ \u00a0]?[A-Z0-9]){10,30}\b")
DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.(?:\d{2}|\d{4}))\b")
PERIOD_RE = re.compile(
    r"(\d{2}\.\d{2}\.(?:\d{2}|\d{4})).{0,40}?(\d{2}\.\d{2}\.(?:\d{2}|\d{4}))"
)
AMOUNT_RE = re.compile(r"[-+]?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}")


@dataclass(frozen=True)
class ParsedTransaction:
    fields: dict[str, str]
    booking_date: date
    value_date: date
    amount_cents: int
    direction: str
    signature_fields: tuple[str, ...]


@dataclass(frozen=True)
class ParsedDKBFile:
    account_iban: str
    account_type: str
    export_from: date
    export_to: date
    reported_balance_cents: int
    reported_balance_date: date
    transactions: list[ParsedTransaction]
    file_sha256: str


def normalize_iban(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def parse_german_date(value: str) -> date:
    parts = value.strip().split(".")
    if len(parts) != 3:
        raise ValueError("date")
    day, month, year = (int(part) for part in parts)
    if year < 100:
        year += 2000
    return date(year, month, day)


def parse_euro_cents(value: str) -> int:
    cleaned = (
        value.replace("\u00a0", "")
        .replace("\u202f", "")
        .replace("€", "")
        .replace("EUR", "")
        .replace(" ", "")
        .strip()
    )
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("amount") from exc
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def canonicalize_field(header: str, value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if header in {"Buchungsdatum", "Wertstellung"}:
        return parse_german_date(normalized).isoformat()
    if header == "Betrag (€)":
        return str(parse_euro_cents(normalized))
    if header == "IBAN":
        return normalize_iban(normalized)
    return normalized


def _metadata_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows)


def _find_metadata(rows: list[list[str]]) -> tuple[str, str, date, date, int, date]:
    text = _metadata_text(rows).replace("\u00a0", " ")
    iban_matches = IBAN_RE.findall(text.upper())
    if not iban_matches:
        raise ValidationError("import_metadata", "error.import_metadata")
    account_iban = normalize_iban(iban_matches[0])

    lower = text.casefold()
    account_type = "girokonto" if "giro" in lower else ""
    periods = PERIOD_RE.findall(text)
    if not periods:
        dates = DATE_RE.findall(text)
        periods = [(dates[0], dates[1])] if len(dates) >= 2 else []
    balance_candidates: list[tuple[int, date]] = []
    for row in rows:
        row_text = " | ".join(row).replace("\u00a0", " ")
        if "saldo" in row_text.casefold() or "kontostand" in row_text.casefold():
            amount_match = AMOUNT_RE.search(row_text)
            date_match = DATE_RE.search(row_text)
            if amount_match and date_match:
                try:
                    balance_candidates.append(
                        (parse_euro_cents(amount_match.group(0)), parse_german_date(date_match.group(1)))
                    )
                except ValueError:
                    pass
    if not account_type or not periods or not balance_candidates:
        raise ValidationError("import_metadata", "error.import_metadata")
    try:
        export_from, export_to = parse_german_date(periods[0][0]), parse_german_date(periods[0][1])
    except ValueError as exc:
        raise ValidationError("import_metadata", "error.import_metadata") from exc
    if export_from > export_to:
        export_from, export_to = export_to, export_from
    balance, balance_date = balance_candidates[0]
    return account_iban, account_type, export_from, export_to, balance, balance_date


def _align_export_period(
    export_from: date,
    export_to: date,
    balance_date: date,
    transactions: list[ParsedTransaction],
) -> tuple[date, date]:
    first_transaction = min(transaction.booking_date for transaction in transactions)
    last_transaction = max(transaction.booking_date for transaction in transactions)

    def contains_period(start: date, end: date) -> bool:
        return start <= first_transaction and last_transaction <= end and start <= balance_date <= end

    if contains_period(export_from, export_to):
        return export_from, export_to

    year_shift = balance_date.year - export_to.year
    try:
        shifted_from = export_from.replace(year=export_from.year + year_shift)
        shifted_to = export_to.replace(year=export_to.year + year_shift)
    except ValueError as exc:
        raise ValidationError("import_metadata", "error.import_metadata") from exc
    if contains_period(shifted_from, shifted_to):
        return shifted_from, shifted_to
    raise ValidationError("import_metadata", "error.import_metadata")


def parse_dkb_csv(data: bytes, max_bytes: int = 10 * 1024 * 1024) -> ParsedDKBFile:
    if len(data) > max_bytes:
        raise ValidationError("import_too_large", "error.import_too_large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("import_encoding", "error.import_encoding") from exc
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";", quotechar='"'))
    except csv.Error as exc:
        raise ValidationError("import_layout", "error.import_layout") from exc
    header_index = next(
        (index for index, row in enumerate(rows) if [cell.strip() for cell in row] == HEADERS),
        None,
    )
    if header_index is None:
        raise ValidationError("import_layout", "error.import_layout")
    metadata_rows = rows[:header_index]
    account_iban, account_type, export_from, export_to, balance, balance_date = _find_metadata(
        metadata_rows
    )
    parsed: list[ParsedTransaction] = []
    for row in rows[header_index + 1 :]:
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) != len(HEADERS):
            raise ValidationError("import_row", "error.import_row")
        fields = dict(zip(HEADERS, row, strict=True))
        if fields["Status"].strip() != "Gebucht":
            raise ValidationError("unsupported_status", "error.import_status")
        try:
            booking_date = parse_german_date(fields["Buchungsdatum"])
            value_date = parse_german_date(fields["Wertstellung"])
            amount_cents = parse_euro_cents(fields["Betrag (€)"])
            canonical = tuple(canonicalize_field(header, fields[header]) for header in HEADERS)
        except (ValueError, OverflowError) as exc:
            raise ValidationError("import_row", "error.import_row") from exc
        # DKB's aggregate convention groups a booked zero-value information row
        # with incoming rows. The signed amount remains zero, so callers can
        # still identify it without inventing a third bank direction.
        direction = "incoming" if amount_cents >= 0 else "outgoing"
        parsed.append(
            ParsedTransaction(fields, booking_date, value_date, amount_cents, direction, canonical)
        )
    if not parsed:
        raise ValidationError("import_layout", "error.import_layout")
    export_from, export_to = _align_export_period(
        export_from,
        export_to,
        balance_date,
        parsed,
    )
    return ParsedDKBFile(
        account_iban=account_iban,
        account_type=account_type,
        export_from=export_from,
        export_to=export_to,
        reported_balance_cents=balance,
        reported_balance_date=balance_date,
        transactions=parsed,
        file_sha256=hashlib.sha256(data).hexdigest(),
    )


def transaction_signature(account_id: str, canonical_fields: tuple[str, ...]) -> str:
    payload = "\x1f".join((account_id, *canonical_fields)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def occurrence_signatures(account_id: str, parsed: ParsedDKBFile) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    result: list[tuple[str, int]] = []
    for transaction in parsed.transactions:
        signature = transaction_signature(account_id, transaction.signature_fields)
        occurrence = counts[signature]
        counts[signature] += 1
        result.append((signature, occurrence))
    return result


def display_counterparty(fields: dict[str, str], amount_cents: int) -> str:
    candidates = (
        (fields.get("Zahlungspflichtige*r", ""), fields.get("Zahlungsempfänger*in", ""))
        if amount_cents >= 0
        else (fields.get("Zahlungsempfänger*in", ""), fields.get("Zahlungspflichtige*r", ""))
    )
    return next((candidate.strip() for candidate in candidates if candidate.strip()), fields.get("Umsatztyp", "").strip())


def audit_payload(fields: dict[str, str]) -> dict[str, Any]:
    return {header: fields.get(header, "") for header in HEADERS}
