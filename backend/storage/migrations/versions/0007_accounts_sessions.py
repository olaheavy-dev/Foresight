"""Accounts, browser sessions and workspace ownership (docs/05 §5.9, owner decision 15 Oct 2026).

Google sign-in with a guest option: `app_user` (issuer + subject), `auth_session` (only the
SHA-256 of the cookie token is stored) and each workspace's owner (a user or a guest session).
Seeded demo workspaces stay as ownerless templates; guests get private `sample` copies.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("issuer", "subject", name="uq_app_user_identity"),
    )
    op.create_table(
        "auth_session",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("active_workspace_id", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_session_user_id", "auth_session", ["user_id"])
    op.add_column(
        "workspace",
        sa.Column(
            "owner_user_id",
            sa.String(32),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "workspace",
        sa.Column(
            "owner_session_id",
            sa.String(32),
            sa.ForeignKey("auth_session.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "workspace", sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_workspace_owner_user_id", "workspace", ["owner_user_id"])
    op.create_index("ix_workspace_owner_session_id", "workspace", ["owner_session_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_owner_session_id", "workspace")
    op.drop_index("ix_workspace_owner_user_id", "workspace")
    op.drop_column("workspace", "last_active_at")
    op.drop_column("workspace", "owner_session_id")
    op.drop_column("workspace", "owner_user_id")
    op.drop_index("ix_auth_session_user_id", "auth_session")
    op.drop_table("auth_session")
    op.drop_table("app_user")
