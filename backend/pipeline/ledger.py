"""Conversions between stored rows and `finance_core` value types."""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

from backend.finance_core import types as t
from backend.finance_core.importers.profiles import FormatProfile
from backend.finance_core.locale import DateFormat
from backend.storage import models as m
from backend.storage.ids import new_id


def transaction(row: m.Transaction) -> t.Transaction:
    return t.Transaction(
        id=row.id,
        account_id=row.account_id,
        posted_on=row.posted_on,
        amount_minor=row.amount_minor,
        currency=row.currency,
        description=row.description,
        normalised=row.normalised,
        channel=t.Channel(row.channel),
        counterparty=row.counterparty,
        external_id=row.external_id,
        balance_after_minor=row.balance_after_minor,
        bank_category=row.bank_category,
        source_row_index=row.source_row_index,
    )


def categorisation(row: m.Categorisation) -> t.Categorisation:
    return t.Categorisation(
        transaction_id=row.transaction_id,
        category_key=row.category_key,
        flow_kind=t.FlowKind(row.flow_kind),
        method=t.CategorisationMethod(row.method),
        confidence=row.confidence,
        rationale=row.rationale,
    )


def categorisation_row(c: t.Categorisation, supersedes: str | None = None) -> m.Categorisation:
    return m.Categorisation(
        id=new_id("ctg"),
        transaction_id=c.transaction_id,
        category_key=c.category_key,
        flow_kind=c.flow_kind.value,
        method=c.method.value,
        confidence=float(c.confidence),
        rationale=c.rationale,
        supersedes=supersedes,
    )


def raw_cells(row: t.ParsedRow) -> dict[str, Any]:
    """The parsed fields of a source row, as JSON (the importer does not keep raw cells)."""
    return {
        "date": row.posted_on.isoformat(),
        "time": row.posted_time.isoformat() if row.posted_time else None,
        "description": row.description,
        "amount_minor": row.amount_minor,
        "currency": row.currency,
        "balance_after_minor": row.balance_after_minor,
        "external_id": row.external_id,
        "bank_category": row.bank_category,
        "bank_type": row.bank_type,
    }


# ------------------------------------------------------------------------- payday rule


def payday_rule_json(rule: t.PaydayRule | None) -> dict[str, Any] | None:
    if rule is None:
        return None
    return {
        "kind": rule.kind,
        "day_of_month": rule.day_of_month,
        "anchor_date": rule.anchor_date.isoformat() if rule.anchor_date else None,
        "december_day": rule.december_day,
    }


def payday_rule(data: dict[str, Any] | None) -> t.PaydayRule | None:
    if data is None:
        return None
    anchor = data.get("anchor_date")
    return t.PaydayRule(
        kind=data["kind"],
        day_of_month=data.get("day_of_month"),
        anchor_date=date.fromisoformat(anchor) if anchor else None,
        december_day=data.get("december_day"),
    )


# ------------------------------------------------------------------------- detections


def income_row(s: t.IncomeStream) -> m.IncomeStream:
    return m.IncomeStream(
        id=new_id("inc"),
        key=s.key,
        source_label=s.source,
        amount_minor=s.amount_minor,
        currency=s.currency,
        cadence=s.cadence.value,
        payday_rule=payday_rule_json(s.payday_rule),
        provenance=s.provenance.value,
        member_ids=list(s.member_ids),
        irregular_amounts_minor=list(s.irregular_amounts_minor),
    )


def income_stream(row: m.IncomeStream) -> t.IncomeStream:
    return t.IncomeStream(
        key=row.key,
        source=row.source_label,
        amount_minor=row.amount_minor,
        currency=row.currency,
        cadence=t.Cadence(row.cadence),
        payday_rule=payday_rule(row.payday_rule),
        provenance=t.Provenance(row.provenance),
        member_ids=tuple(row.member_ids),
        irregular_amounts_minor=tuple(row.irregular_amounts_minor),
    )


def obligation_row(o: t.RecurringObligation) -> m.RecurringObligation:
    return m.RecurringObligation(
        id=new_id("rob"),
        key=o.key,
        label=o.label,
        category_key=o.category_key,
        flow_kind=o.flow_kind.value,
        amount_minor=o.amount_minor,
        currency=o.currency,
        cadence=o.cadence.value,
        anchor_day=o.anchor_day,
        active_months=sorted(o.active_months),
        member_ids=list(o.member_ids),
        is_commitment=o.is_commitment,
        provenance="detected",
    )


def obligation(row: m.RecurringObligation) -> t.RecurringObligation:
    return t.RecurringObligation(
        key=row.key,
        label=row.label,
        category_key=row.category_key,
        flow_kind=t.FlowKind(row.flow_kind),
        amount_minor=row.amount_minor,
        currency=row.currency,
        cadence=t.Cadence(row.cadence),
        anchor_day=row.anchor_day,
        active_months=frozenset(row.active_months),
        member_ids=tuple(row.member_ids),
        is_commitment=row.is_commitment,
    )


# ------------------------------------------------------------------------- format profiles


def profile_json(p: FormatProfile) -> dict[str, Any]:
    data = dataclasses.asdict(p)
    data["columns"] = {role: list(names) for role, names in p.columns.items()}
    return data


def profile(data: dict[str, Any]) -> FormatProfile:
    fmt = data.get("date_format")
    return FormatProfile(
        profile_id=data["profile_id"],
        label=data["label"],
        header_signature=tuple(data["header_signature"]),
        columns={role: tuple(names) for role, names in data["columns"].items()},
        date_format=DateFormat(**fmt) if fmt else None,
        decimal_sep=data.get("decimal_sep"),
        group_sep=data.get("group_sep"),
        sign_convention=data.get("sign_convention", "signed"),
        skip_zero_amount=bool(data.get("skip_zero_amount", False)),
        currency=data.get("currency"),
        origin=data.get("origin", "proposed"),
        notes=tuple(data.get("notes", ())),
    )
