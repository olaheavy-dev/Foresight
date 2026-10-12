"""Fail if a built container image could leak secrets or private data.

Images are published to GHCR (publicly readable), so before anything is pushed this checks each
image's (1) environment variables, by name and by value, and (2) application files for .env files,
private keys and statement files. Runtime secrets belong only in the server's .env, never in an
image. Usage: python -m tools.check_image_secrets <image> [<image> ...]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable

# Variable names that suggest a secret. Base images set a few public values that match; those
# are allow-listed by exact name.
SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE)", re.IGNORECASE)
ALLOWED_NAMES = {"GPG_KEY"}  # official python image: public key fingerprint used to verify Python
SECRET_VALUE = re.compile(
    r"(rsk_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|://[^/\s:@]+:[^/\s@]+@)"
)

# Only application directories are scanned for files; dependency trees legitimately ship
# fixtures (e.g. .env.example files inside packages).
APP_ROOTS = ("srv/", "app/")
SKIP_PARTS = ("node_modules/", "site-packages/", "__pycache__/")
FORBIDDEN_FILE = re.compile(
    r"(^|/)(\.env(\.[^/]*)?|id_rsa|id_ed25519|[^/]*\.pem|[^/]*\.key|[^/]*\.p12"
    r"|[^/]*\.(pdf|csv|xls|xlsx))$",
    re.IGNORECASE,
)
ALLOWED_FILES = re.compile(r"(^|/)\.env\.example$")


def env_findings(env: Iterable[str]) -> list[str]:
    findings = []
    for entry in env:
        name, _, value = entry.partition("=")
        if SECRET_NAME.search(name) and name not in ALLOWED_NAMES:
            findings.append(f"environment variable {name} looks like a secret")
        if SECRET_VALUE.search(value):
            findings.append(f"environment variable {name} has a secret-looking value")
    return findings


def path_findings(paths: Iterable[str]) -> list[str]:
    findings = []
    for raw in paths:
        path = raw.removeprefix("./").lstrip("/")
        at_root = "/" not in path
        in_app = path.startswith(APP_ROOTS) and not any(part in path for part in SKIP_PARTS)
        if not (at_root or in_app):
            continue
        if FORBIDDEN_FILE.search(path) and not ALLOWED_FILES.search(path):
            findings.append(f"file {path} must not be in an image")
    return findings


def _docker_bin() -> str:
    path = shutil.which("docker")
    if path is None:
        raise SystemExit("docker CLI not found")
    return path


def _docker(*args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed docker CLI invocation
        [_docker_bin(), *args], check=True, capture_output=True, text=True
    ).stdout


def image_env(image: str) -> list[str]:
    out = _docker(
        "image", "inspect", image, "--format", "{{range .Config.Env}}{{println .}}{{end}}"
    )
    return [line for line in out.splitlines() if line]


def image_paths(image: str) -> list[str]:
    container = _docker("create", image).strip()
    try:
        with tempfile.TemporaryFile() as archive:
            subprocess.run(  # noqa: S603 - fixed docker CLI invocation
                [_docker_bin(), "export", container], check=True, stdout=archive
            )
            archive.seek(0)
            with tarfile.open(fileobj=archive) as tar:
                return tar.getnames()
    finally:
        _docker("rm", container)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+")
    args = parser.parse_args(argv)

    failed = False
    for image in args.images:
        findings = env_findings(image_env(image)) + path_findings(image_paths(image))
        for finding in findings:
            print(f"{image}: {finding}", file=sys.stderr)
        failed = failed or bool(findings)
        if not findings:
            print(f"{image}: no secrets or private files found")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
