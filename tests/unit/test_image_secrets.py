"""The image guard blocks secrets and private files before anything is published to GHCR."""

from __future__ import annotations

import pytest

from tools.check_image_secrets import env_findings, path_findings


def test_clean_runtime_environment_passes() -> None:
    env = [
        "PATH=/usr/local/bin:/usr/bin",
        "GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305",
        "PYTHONUNBUFFERED=1",
        "FORESIGHT_BUILD_SHA=abc1234",
        "NODE_ENV=production",
    ]
    assert env_findings(env) == []


@pytest.mark.parametrize(
    "entry",
    [
        "MESH_API_KEY=anything",
        "POSTGRES_PASSWORD=anything",
        "TELEGRAM_BOT_TOKEN=anything",
        "CLIENT_SECRET=anything",
        "NOTES=" + "rsk_" + "a1b2c3d4e5f6",
        "DATABASE_URL=postgresql://user:" + "pw" + "@db:5432/x",
    ],
)
def test_secret_environment_is_blocked(entry: str) -> None:
    assert env_findings([entry]) != []


@pytest.mark.parametrize(
    "path",
    [
        "app/.env",
        "app/.env.local",
        "srv/.env.production",
        "srv/private/id_rsa",
        "app/certs/server.pem",
        "srv/statement.pdf",
        "srv/exports/monzo.csv",
        "srv/demo-data/P1-base/monzo.csv",
        "srv/demo-data/P1-base/exports/nested/monzo.csv",
        "srv/demo-data/private/exports/monzo.csv",
        "srv/demo-data/P1-base/exports/statement.pdf",
        ".env",
    ],
)
def test_secret_and_statement_files_are_blocked(path: str) -> None:
    assert path_findings([path]) != []


@pytest.mark.parametrize(
    "path",
    [
        "app/server.js",
        "srv/backend/app/main.py",
        "app/node_modules/some-pkg/.env",
        "usr/local/lib/python3.12/site-packages/pkg/data.csv",
        "srv/.env.example",
        "etc/ssl/certs/ca.pem",
        "srv/demo-data/P1-base/exports/monzo.csv",
        "srv/demo-data/P2-base/exports/statement.csv",
    ],
)
def test_normal_and_dependency_files_pass(path: str) -> None:
    assert path_findings([path]) == []
