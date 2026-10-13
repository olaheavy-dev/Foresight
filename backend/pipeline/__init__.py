"""Orchestration between storage and the pure engine (docs/05 §3.1).

Pipeline modules read rows through a WorkspaceContext, convert them to `finance_core` value types,
call the engine and persist what it returns. They never commit: the caller owns the transaction.
"""
