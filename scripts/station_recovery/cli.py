"""Explicit operator command; inspection is read-only by default."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import sys
from pathlib import Path
from uuid import UUID

from .operation import pending_recovery, restore_database, resume_recovery
from .storage import ROOT, RecoveryError, current_security, data_path, inspect_backup, regular_file


def uuid_argument(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use the UUID shown in backup or recovery history") from exc


def password_from_file(path: Path) -> str:
    path = path.expanduser().resolve(strict=True)
    info = regular_file(path)
    if info.st_mode & 0o077 or info.st_size > 1024:
        raise RecoveryError("The operator password file must be private (0600) and contain one password")
    try:
        password = path.read_text(encoding="utf-8").rstrip("\r\n")
    except UnicodeError as exc:
        raise RecoveryError("The private password file must contain UTF-8 text") from exc
    if not 12 <= len(password) <= 200 or "\n" in password or "\r" in password:
        raise RecoveryError("The private password file must contain one password of 12 to 200 characters")
    return password


def main(argv=None) -> int:
    from dotenv import dotenv_values
    from sqlalchemy.exc import SQLAlchemyError

    parser = argparse.ArgumentParser(
        description="Inspect a SQLite backup or explicitly restore it while AI Station is stopped."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--backup-run", type=uuid_argument, help="Inspect this application-owned backup UUID")
    mode.add_argument("--finish", type=uuid_argument, help="Finish an approved, interrupted recovery")
    mode.add_argument(
        "--abort",
        type=uuid_argument,
        help="Abort a prepared recovery only while the original database remains",
    )
    mode.add_argument(
        "--pending", action="store_true", help="Inspect the pending recovery without changing files"
    )
    parser.add_argument("--data-root", type=Path, help="Override the configured application data directory")
    parser.add_argument(
        "--apply", action="store_true", help="Explicitly apply the inspected backup; default is read-only"
    )
    parser.add_argument("--expected-sha256", help="The exact backup digest you reviewed before --apply")
    parser.add_argument(
        "--legacy-owner",
        help="Explicitly assign a pre-account backup's private data to this existing current username",
    )
    parser.add_argument(
        "--operator-password-file",
        type=Path,
        help="Private new-password file, required when current credentials cannot be read",
    )
    args = parser.parse_args(argv)
    if args.apply and (not args.backup_run or not args.expected_sha256):
        parser.error("--apply requires --backup-run and its reviewed --expected-sha256")
    if (args.expected_sha256 or args.operator_password_file) and not args.apply:
        parser.error("--expected-sha256 and --operator-password-file require --apply")
    if args.legacy_owner and not args.apply:
        parser.error("--legacy-owner requires --apply and the reviewed backup digest")
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "host-runner")]
    configuration = {**dotenv_values(ROOT / ".env"), **os.environ}
    root = args.data_root or Path(configuration.get("AI_STATION_DATA_HOST_PATH") or ROOT / "data")
    root = root.expanduser()
    if not root.is_absolute():
        root = ROOT / root
    try:
        root = root.resolve(strict=True)
        # Pure domain helpers must resolve any settings against this explicit
        # host data root, including when invoked from an isolated checkout.
        os.environ["AI_STATION_DATA_DIR"] = str(root)
        if args.pending:
            result = pending_recovery(root)
        elif args.finish or args.abort:
            result = resume_recovery(root, args.finish or args.abort, abort=bool(args.abort))
        elif not args.apply:
            result = inspect_backup(root, args.backup_run)
        else:
            password = (
                password_from_file(args.operator_password_file) if args.operator_password_file else None
            )
            current = data_path(root, "db/ai-station.sqlite", required=False)
            if current_security(current) is None and password is None and sys.stdin.isatty():
                password = getpass.getpass("New operator password (current credentials are unreadable): ")
                if password != getpass.getpass("Confirm new operator password: "):
                    raise RecoveryError("New operator passwords did not match")
            options = {"password": password}
            if args.legacy_owner is not None:
                options["legacy_owner"] = args.legacy_owner
            result = restore_database(root, args.backup_run, args.expected_sha256, **options)
        print(json.dumps({"data_root": str(root), **result}, indent=2, ensure_ascii=False))
        return 0
    except RecoveryError as exc:
        print(
            json.dumps({"error": str(exc), "inspect_pending": "./scripts/restore.sh --pending"}),
            file=sys.stderr,
        )
    except (OSError, ValueError, KeyError, sqlite3.Error, SQLAlchemyError):
        print(
            json.dumps(
                {
                    "error": "Recovery could not confirm local files or database state. Inspect before continuing.",
                    "inspect_pending": "./scripts/restore.sh --pending",
                }
            ),
            file=sys.stderr,
        )
    return 1
