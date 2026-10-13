"""The generic CSV importer (ING-01, ING-01b, docs/07 §5).

Flow per table: locate the table → match a saved or built-in FormatProfile by header signature,
otherwise map columns heuristically (unsure ⇒ ask) → detect currency → infer number and date
formats (ambiguous ⇒ ask) → parse rows exactly → reconcile. Questions that must be answered first
leave the batch uncommitted (no rows returned). Contains no bank-specific code.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import time

from backend.finance_core.importers.builtin_profiles import BUILTIN_PROFILES
from backend.finance_core.importers.profiles import FormatProfile, match_profile, normalise_header
from backend.finance_core.importers.reconcile import reconcile
from backend.finance_core.importers.table_locator import Table, decode, locate_tables
from backend.finance_core.locale import (
    DateFormat,
    LocalePack,
    NumberFormat,
    infer_date_format,
    infer_number_format,
    parse_date,
)
from backend.finance_core.money import MoneyError, detect_currency, exponent, parse_amount
from backend.finance_core.types import (
    ImportResult,
    ParsedRow,
    Question,
    ReconciliationResult,
    ReconciliationStatus,
)

# Questions that block committing the batch. "balance_today" does not block: without a balance
# the forecast runs in relative mode until the user answers.
BLOCKING_KINDS = frozenset({"currency", "date_order", "decimal_separator", "columns"})

SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("date", "transaction date", "posted", "posting date", "value date", "booking date",
             "completed date", "date completed", "started date"),
    "time": ("time",),
    "description": ("description", "details", "narration", "name", "merchant", "payee",
                    "transaction description", "particulars", "memo", "reference"),
    "amount": ("amount", "value", "transaction amount", "money in/out", "in/out"),
    "money_in": ("money in", "paid in", "credit", "credits", "deposit", "deposits", "in"),
    "money_out": ("money out", "paid out", "debit", "debits", "withdrawal", "withdrawals", "out"),
    "balance": ("balance", "running balance", "balance after", "closing balance"),
    "id": ("transaction id", "id", "reference id", "transaction reference"),
    "bank_category": ("category",),
    "bank_type": ("type", "transaction type"),
    "currency": ("currency", "ccy"),
}  # fmt: skip


@dataclass(frozen=True)
class TableImport:
    title: str | None  # e.g. "Personal Account (GBP)": the account/pocket hint
    profile: FormatProfile | None  # resolved profile (save it to make re-imports silent)
    result: ImportResult


def blocking_questions(result: ImportResult) -> tuple[Question, ...]:
    return tuple(q for q in result.questions if q.kind in BLOCKING_KINDS)


# --------------------------------------------------------------------------- column mapping


def _strip_units(header: str) -> str:
    return re.sub(r"\s*\((?:[a-z]{3}|[£€$₹¥])\)\s*$", "", header)


def heuristic_profile(headers: Sequence[str]) -> tuple[FormatProfile | None, Question | None]:
    """Map unknown headers to roles. Confident ⇒ a heuristic profile; unsure ⇒ a Question."""
    norm = [_strip_units(normalise_header(h)) for h in headers]
    columns: dict[str, tuple[str, ...]] = {}
    used: set[int] = set()
    for role in ("id", "date", "time", "money_in", "money_out", "amount", "balance",
                 "bank_category", "bank_type", "currency", "description"):  # fmt: skip
        for idx, name in enumerate(norm):
            if idx in used:
                continue
            if name in SYNONYMS[role]:
                columns[role] = (normalise_header(headers[idx]),)
                used.add(idx)
                break
    has_amount = "amount" in columns or ("money_in" in columns and "money_out" in columns)
    confident = "date" in columns and "description" in columns and has_amount
    if not confident:
        proposal = ", ".join(f"{r} = {c[0]}" for r, c in columns.items()) or "no columns recognised"
        return None, Question(
            kind="columns",
            prompt=f"Please confirm the columns in this file (proposed: {proposal}).",
            options=tuple(normalise_header(h) for h in headers),
        )
    # Split in/out columns win; a signed amount column alongside them is kept as a cross-check.
    convention = "in_out" if "money_in" in columns and "money_out" in columns else "signed"
    return (
        FormatProfile(
            profile_id="heuristic." + hashlib.sha256("|".join(norm).encode()).hexdigest()[:12],
            label="Recognised columns",
            header_signature=tuple(normalise_header(h) for h in headers if h.strip()),
            columns=columns,
            sign_convention=convention,
            skip_zero_amount=True,
            origin="heuristic",
        ),
        None,
    )


def _cell(headers: Sequence[str], cells: Sequence[str], names: Sequence[str]) -> str:
    norm = [normalise_header(h) for h in headers]
    for name in names:
        if name in norm:
            value = cells[norm.index(name)].strip() if norm.index(name) < len(cells) else ""
            if value:
                return value
    return ""


def _parse_time(text: str) -> time | None:
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?", text.strip())
    if not m:
        return None
    return time(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


# --------------------------------------------------------------------------- one table


def import_table(
    table: Table,
    *,
    pack: LocalePack,
    home_currency: str,
    saved_profiles: Sequence[FormatProfile] = (),
    answers: Mapping[str, str] | None = None,
    file_sha256: str = "",
) -> TableImport:
    answers = dict(answers or {})
    warnings: list[str] = []
    profile = match_profile(table.headers, list(saved_profiles) + list(BUILTIN_PROFILES))
    if profile is None:
        profile, question = heuristic_profile(table.headers)
        if profile is None:
            assert question is not None
            return _pending(table, None, (question,), file_sha256)
    cols = profile.columns
    amount_names = cols.get("amount", ()) + cols.get("money_in", ()) + cols.get("money_out", ())
    amount_samples = [_cell(table.headers, c, amount_names) for _, c in table.rows[:200]]
    amount_samples = [s for s in amount_samples if s]

    currency_values = [_cell(table.headers, c, cols.get("currency", ())) for _, c in table.rows]
    currency: str | None
    if "currency" in answers:
        currency, provenance, cq = answers["currency"].upper(), "user_confirmed", None
    else:
        currency, provenance, cq = detect_currency(
            currency_column_values=currency_values,
            amount_samples=amount_samples,
            header_text=table.title or "",
            profile_currency=profile.currency,
            home_currency=home_currency,
        )
    questions: list[Question] = [cq] if cq else []

    if profile.decimal_sep is not None:
        number_format: NumberFormat | None = NumberFormat(
            profile.decimal_sep, profile.group_sep or "", "thousands"
        )
    elif "decimal_separator" in answers:
        dec = answers["decimal_separator"]
        number_format = NumberFormat(dec, "." if dec == "," else ",", "thousands")
    else:
        exp = exponent(currency) if currency else 2
        number_format, nq = infer_number_format(amount_samples, exp)
        if nq:
            questions.append(nq)

    date_samples = [_cell(table.headers, c, cols.get("date", ())) for _, c in table.rows]
    date_samples = [s for s in date_samples if s]
    if "date_order" in answers:
        sample_has_names = any(re.search(r"[A-Za-z]", s) for s in date_samples)
        date_format: DateFormat | None = DateFormat(answers["date_order"], sample_has_names)
    else:
        date_format, dq = infer_date_format(date_samples, pack, saved=profile.date_format)
        if dq:
            questions.append(dq)

    if questions or currency is None or number_format is None or date_format is None:
        return _pending(table, profile, tuple(questions), file_sha256)

    resolved = replace(
        profile,
        date_format=date_format,
        decimal_sep=number_format.decimal_sep,
        group_sep=number_format.group_sep,
        currency=profile.currency or (currency if provenance != "home_default" else None),
        origin="user_confirmed" if answers and profile.origin != "builtin" else profile.origin,
    )

    rows: list[ParsedRow] = []
    errors: list[str] = []
    disagreements: list[str] = []
    skipped_zero = 0
    for file_row, cells in table.rows:
        try:
            row = _parse_row(table.headers, cells, file_row, resolved, currency, number_format,
                             date_format, pack)  # fmt: skip
            mismatch = _redundant_amounts_disagree(
                table.headers, cells, resolved, currency, number_format
            )
        except (MoneyError, ValueError) as exc:
            errors.append(f"row {file_row}: {exc}")
            continue
        if row is None:
            continue
        if mismatch:
            disagreements.append(f"row {file_row}: {mismatch}")
        if row.amount_minor == 0 and resolved.skip_zero_amount:
            skipped_zero += 1
            continue
        rows.append(row)
    if skipped_zero:
        warnings.append(f"{skipped_zero} zero-value rows skipped (e.g. card checks)")

    if errors:
        rec = ReconciliationResult(ReconciliationStatus.FAILED, len(table.rows), len(errors),
                                   tuple(errors))  # fmt: skip
        return TableImport(table.title, resolved, _result((), resolved, currency, provenance,
                                                          date_format, rec, (), warnings,
                                                          file_sha256))  # fmt: skip
    rec = reconcile(rows, resolved.has_balance)
    if disagreements:
        # The file states each amount twice and the two disagree (e.g. the sign convention is
        # inverted): we can't know which is right, so nothing from this table is committed.
        failures = tuple(disagreements) + rec.failures
        rec = ReconciliationResult(
            ReconciliationStatus.FAILED, rec.rows_checked, len(failures), failures
        )
    out_rows: tuple[ParsedRow, ...] = (
        tuple(rows) if rec.status != ReconciliationStatus.FAILED else ()
    )
    late_questions: tuple[Question, ...] = ()
    if not resolved.has_balance:
        late_questions = (
            Question(
                kind="balance_today",
                prompt="This export doesn't include a balance. What's in the account today?",
            ),
        )
    return TableImport(
        table.title,
        resolved,
        _result(
            out_rows,
            resolved,
            currency,
            provenance,
            date_format,
            rec,
            late_questions,
            warnings,
            file_sha256,
        ),  # fmt: skip
    )


def _parse_row(
    headers: Sequence[str],
    cells: Sequence[str],
    file_row: int,
    profile: FormatProfile,
    currency: str,
    nf: NumberFormat,
    df: DateFormat,
    pack: LocalePack,
) -> ParsedRow | None:
    cols = profile.columns
    date_text = _cell(headers, cells, cols.get("date", ()))
    if not date_text:
        return None
    posted_on = parse_date(date_text, df, pack.month_names)

    def amount(names: Sequence[str]) -> int | None:
        text = _cell(headers, cells, names)
        return parse_amount(text, currency, nf.decimal_sep, nf.group_sep) if text else None

    if profile.sign_convention == "in_out":
        money_in = amount(cols.get("money_in", ())) or 0
        money_out = amount(cols.get("money_out", ())) or 0
        value = abs(money_in) - abs(money_out)
    else:
        parsed = amount(cols.get("amount", ()))
        if parsed is None:
            raise ValueError("missing amount")
        value = parsed
    balance = amount(cols.get("balance", ()))
    return ParsedRow(
        source_row_index=file_row,
        posted_on=posted_on,
        description=_cell(headers, cells, cols.get("description", ())),
        amount_minor=value,
        currency=currency,
        balance_after_minor=balance,
        external_id=_cell(headers, cells, cols.get("id", ())) or None,
        bank_category=_cell(headers, cells, cols.get("bank_category", ())) or None,
        bank_type=_cell(headers, cells, cols.get("bank_type", ())) or None,
        posted_time=_parse_time(_cell(headers, cells, cols.get("time", ()))),
    )


def _redundant_amounts_disagree(
    headers: Sequence[str],
    cells: Sequence[str],
    profile: FormatProfile,
    currency: str,
    nf: NumberFormat,
) -> str | None:
    """Some exports state each amount twice: a signed amount and split money in / money out
    columns. When both are filled for a row they must give the same signed value; a mismatch means
    the columns or the sign convention aren't what the profile says."""
    cols = profile.columns
    names = (cols.get("amount", ()), cols.get("money_in", ()), cols.get("money_out", ()))
    if not all(names):
        return None
    texts = [_cell(headers, cells, n) for n in names]
    if not texts[0] or not (texts[1] or texts[2]):
        return None
    signed, money_in, money_out = (
        parse_amount(t, currency, nf.decimal_sep, nf.group_sep) if t else 0 for t in texts
    )
    split = abs(money_in) - abs(money_out)
    if signed == split:
        return None
    return (
        f"amount {texts[0]} disagrees with money in/out ({texts[1] or '-'} / {texts[2] or '-'}); "
        "the sign convention or columns don't match this format"
    )


def _result(
    rows: tuple[ParsedRow, ...],
    profile: FormatProfile | None,
    currency: str | None,
    provenance: str,
    date_format: DateFormat | None,
    rec: ReconciliationResult,
    questions: tuple[Question, ...],
    warnings: Sequence[str],
    file_sha256: str,
) -> ImportResult:
    return ImportResult(
        rows=rows,
        format_profile_id=profile.profile_id if profile else None,
        detected_currency=currency,
        currency_provenance=provenance,
        date_format=date_format.describe() if date_format else None,
        reconciliation=rec,
        questions=questions,
        warnings=tuple(warnings),
        file_sha256=file_sha256,
    )


def _pending(
    table: Table, profile: FormatProfile | None, questions: tuple[Question, ...], sha: str
) -> TableImport:
    rec = ReconciliationResult(
        ReconciliationStatus.NOT_RECONCILABLE, 0, 0, ("waiting for answers before importing",)
    )
    return TableImport(
        table.title, profile, _result((), profile, None, "pending", None, rec, questions, (), sha)
    )


# --------------------------------------------------------------------------- whole file


def import_csv(
    data: bytes,
    *,
    pack: LocalePack,
    home_currency: str,
    saved_profiles: Sequence[FormatProfile] = (),
    answers: Mapping[str, str] | None = None,
) -> tuple[tuple[TableImport, ...], tuple[str, ...]]:
    """All tables in a CSV file. Tables with no rows (e.g. an empty currency pocket) are skipped
    with a warning."""
    sha = hashlib.sha256(data).hexdigest()
    tables = locate_tables(decode(data))
    warnings: list[str] = []
    if not tables:
        warnings.append("No transaction table found in this file.")
    out: list[TableImport] = []
    for table in tables:
        if not table.rows:
            warnings.append(f"Skipped an empty table ({table.title or 'untitled'}).")
            continue
        out.append(
            import_table(
                table,
                pack=pack,
                home_currency=home_currency,
                saved_profiles=saved_profiles,
                answers=answers,
                file_sha256=sha,
            )
        )
    return tuple(out), tuple(warnings)
