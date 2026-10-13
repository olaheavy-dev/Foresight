"""Workspace-scoped data access (docs/07 §7).

Every read and write goes through a `WorkspaceContext`, which adds `workspace_id` to each query and
stamps it on each new row. A row from another workspace is invisible (reads return nothing), and
adding one raises `CrossWorkspaceError`. Composite foreign keys enforce the same rule in the
database. This module imports only SQLAlchemy and the standard library (docs/05 §3.1).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from backend.storage import models as m
from backend.storage.ids import new_id

Row = TypeVar("Row", bound=m.Base)

GENESIS_HASH = "0" * 64


class WorkspaceNotFound(LookupError):
    pass


class CrossWorkspaceError(PermissionError):
    pass


def audit_hash(prev_hash: str, body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def _audit_body(event: m.AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "workspace_id": event.workspace_id,
        "seq": event.seq,
        "actor": event.actor,
        "action": event.action,
        "subject_type": event.subject_type,
        "subject_id": event.subject_id,
        "before": event.before,
        "after": event.after,
        "run_id": event.run_id,
        "occurred_at": event.occurred_at,
    }


@dataclass
class WorkspaceContext:
    session: Session
    workspace_id: str

    @classmethod
    def open(cls, session: Session, workspace_id: str) -> WorkspaceContext:
        if session.get(m.Workspace, workspace_id) is None:
            raise WorkspaceNotFound(workspace_id)
        return cls(session, workspace_id)

    # ----------------------------------------------------------------- generic, always scoped

    @property
    def workspace(self) -> m.Workspace:
        ws = self.session.get(m.Workspace, self.workspace_id)
        if ws is None:
            raise WorkspaceNotFound(self.workspace_id)
        return ws

    def select(self, model: type[Row]) -> Select[tuple[Row]]:
        column = model.__table__.c.workspace_id
        return select(model).where(column == self.workspace_id)

    def get(self, model: type[Row], row_id: str) -> Row | None:
        row = self.session.get(model, row_id)
        if row is None or getattr(row, "workspace_id", None) != self.workspace_id:
            return None
        return row

    def all(self, model: type[Row]) -> list[Row]:
        return list(self.session.scalars(self.select(model)))

    def add(self, row: m.Base) -> None:
        current = getattr(row, "workspace_id", None)
        if current is not None and current != self.workspace_id:
            raise CrossWorkspaceError(f"row belongs to {current}, not {self.workspace_id}")
        row.workspace_id = self.workspace_id  # type: ignore[attr-defined]
        self.session.add(row)

    def add_all(self, rows: Iterable[m.Base]) -> None:
        for row in rows:
            self.add(row)

    def bump_data_version(self) -> int:
        ws = self.workspace
        ws.data_version = (ws.data_version or 0) + 1
        return ws.data_version

    # ----------------------------------------------------------------- ledger

    def account(self, account_id: str) -> m.Account:
        acct = self.get(m.Account, account_id)
        if acct is None:
            raise CrossWorkspaceError(f"no account {account_id} in {self.workspace_id}")
        return acct

    def account_by_source_key(self, source_key: str) -> m.Account | None:
        stmt = self.select(m.Account).where(m.Account.source_key == source_key)
        return self.session.scalars(stmt).first()

    def committed_batch(
        self, account_id: str, file_sha256: str, table_index: int
    ) -> m.ImportBatch | None:
        stmt = self.select(m.ImportBatch).where(
            m.ImportBatch.account_id == account_id,
            m.ImportBatch.file_sha256 == file_sha256,
            m.ImportBatch.table_index == table_index,
            m.ImportBatch.status == "committed",
        )
        return self.session.scalars(stmt).first()

    def fingerprints(self, account_id: str) -> set[str]:
        stmt = select(m.Transaction.fingerprint).where(
            m.Transaction.workspace_id == self.workspace_id,
            m.Transaction.account_id == account_id,
        )
        return set(self.session.scalars(stmt))

    def transactions(
        self, account_ids: Sequence[str] | None = None, currency: str | None = None
    ) -> list[m.Transaction]:
        stmt = self.select(m.Transaction).where(m.Transaction.status == "active")
        if account_ids is not None:
            stmt = stmt.where(m.Transaction.account_id.in_(account_ids))
        if currency is not None:
            stmt = stmt.where(m.Transaction.currency == currency)
        stmt = stmt.order_by(m.Transaction.posted_on, m.Transaction.account_id, m.Transaction.id)
        return list(self.session.scalars(stmt))

    def latest_categorisations(self) -> dict[str, m.Categorisation]:
        """transaction_id → its latest categorisation (append-only history, latest wins)."""
        latest = (
            select(m.Categorisation.transaction_id, func.max(m.Categorisation.seq).label("seq"))
            .where(m.Categorisation.workspace_id == self.workspace_id)
            .group_by(m.Categorisation.transaction_id)
            .subquery()
        )
        stmt = select(m.Categorisation).join(latest, m.Categorisation.seq == latest.c.seq)
        return {c.transaction_id: c for c in self.session.scalars(stmt)}

    def counterparties(self) -> dict[str, m.Counterparty]:
        return {c.key: c for c in self.all(m.Counterparty)}

    def anchors(self, account_id: str) -> list[m.BalanceAnchor]:
        stmt = (
            self.select(m.BalanceAnchor)
            .where(m.BalanceAnchor.account_id == account_id)
            .order_by(m.BalanceAnchor.as_of, m.BalanceAnchor.created_at)
        )
        return list(self.session.scalars(stmt))

    def upsert_anchor(
        self,
        account_id: str,
        as_of: date,
        amount_minor: int,
        currency: str,
        source: str,
        provenance: str,
        import_batch_id: str | None = None,
    ) -> m.BalanceAnchor:
        self.account(account_id)
        stmt = self.select(m.BalanceAnchor).where(
            m.BalanceAnchor.account_id == account_id,
            m.BalanceAnchor.as_of == as_of,
            m.BalanceAnchor.source == source,
        )
        anchor = self.session.scalars(stmt).first()
        if anchor is None:
            anchor = m.BalanceAnchor(
                id=new_id("bal"),
                account_id=account_id,
                as_of=as_of,
                amount_minor=amount_minor,
                currency=currency,
                source=source,
                provenance=provenance,
                import_batch_id=import_batch_id,
            )
            self.add(anchor)
        else:
            anchor.amount_minor = amount_minor
            anchor.provenance = provenance
        return anchor

    # ----------------------------------------------------------------- detections

    def replace_detected(
        self,
        model: type[m.IncomeStream] | type[m.RecurringObligation],
        rows: Sequence[m.IncomeStream] | Sequence[m.RecurringObligation],
    ) -> None:
        """Swap detected rows for a fresh detection; confirmed and declared rows are kept, and a
        detection never overwrites a key the user has confirmed or declared."""
        kept = set(
            self.session.scalars(
                select(model.key).where(
                    model.workspace_id == self.workspace_id, model.provenance != "detected"
                )
            )
        )
        self.session.execute(
            delete(model).where(
                model.workspace_id == self.workspace_id, model.provenance == "detected"
            )
        )
        self.session.flush()
        self.add_all(r for r in rows if r.key not in kept)

    # ----------------------------------------------------------------- calculations

    def calculation(self, calc_id: str) -> m.Calculation | None:
        return self.get(m.Calculation, calc_id)

    def latest_calculation(self, kind: str) -> m.Calculation | None:
        stmt = (
            self.select(m.Calculation)
            .where(m.Calculation.kind == kind)
            .order_by(m.Calculation.created_at.desc())
        )
        return self.session.scalars(stmt).first()

    # ----------------------------------------------------------------- audit

    def append_audit(
        self,
        action: str,
        subject_type: str,
        subject_id: str,
        *,
        actor: str = "system",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> m.AuditEvent:
        # Serialise appenders per workspace so the chain never forks.
        self.session.execute(
            select(m.Workspace.id).where(m.Workspace.id == self.workspace_id).with_for_update()
        )
        last = self.session.scalars(
            self.select(m.AuditEvent).order_by(m.AuditEvent.seq.desc()).limit(1)
        ).first()
        event = m.AuditEvent(
            id=new_id("aud"),
            workspace_id=self.workspace_id,
            seq=(last.seq if last else 0) + 1,
            actor=actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            before=before,
            after=after,
            run_id=run_id,
            occurred_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            prev_hash=last.hash if last else GENESIS_HASH,
        )
        event.hash = audit_hash(event.prev_hash, _audit_body(event))
        self.add(event)
        self.session.flush()
        return event

    def audit_chain_valid(self) -> bool:
        events = self.session.scalars(self.select(m.AuditEvent).order_by(m.AuditEvent.seq))
        prev = GENESIS_HASH
        for expected_seq, event in enumerate(events, start=1):
            if event.seq != expected_seq or event.prev_hash != prev:
                return False
            if audit_hash(prev, _audit_body(event)) != event.hash:
                return False
            prev = event.hash
        return True


def create_workspace(
    session: Session,
    *,
    name: str,
    country: str,
    home_currency: str,
    locale: str,
    timezone_name: str,
    kind: str = "user",
    persona_key: str | None = None,
    buffer_minor: int | None = None,
) -> WorkspaceContext:
    ws = m.Workspace(
        id=new_id("wsp"),
        name=name,
        country=country,
        home_currency=home_currency,
        locale=locale,
        timezone=timezone_name,
        kind=kind,
        persona_key=persona_key,
        buffer_minor=buffer_minor,
        data_version=0,
    )
    session.add(ws)
    session.flush()
    return WorkspaceContext(session, ws.id)


def demo_workspace(session: Session, persona_key: str) -> m.Workspace | None:
    stmt = select(m.Workspace).where(
        m.Workspace.kind == "demo", m.Workspace.persona_key == persona_key
    )
    return session.scalars(stmt).first()
