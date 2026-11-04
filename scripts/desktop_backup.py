"""Offline Mac installer backup utility. Consumer setup remains separately gated."""

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from uuid import uuid4

# The installed interpreter runs isolated; import this verified payload only.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None):
    import desktop
    import desktop_snapshots as snapshots
    import desktop_versions as versions
    from desktop_engine import select
    from macos_database_storage import RECEIPT, DatabaseStorage

    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    check = actions.add_parser("verify", help="Verify a full backup without Docker or changing data")
    check.add_argument("backup", type=Path)
    for name in ("export", "cancel", "restore", "resume-restore", "abort-restore"):
        action = actions.add_parser(name)
        action.add_argument("--config", type=Path, required=True)
        action.add_argument("--package", type=Path, required=True)
        action.add_argument("--operation", required=name in {"cancel", "resume-restore", "abort-restore"})
        if name == "restore":
            action.add_argument("--backup", type=Path, required=True)
            action.add_argument("--keep-current-credentials", action="store_true")
            action.add_argument("--recover-administrator")
            action.add_argument("--admin-password-stdin", action="store_true")
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.action == "verify":
        result = snapshots.verify(args.backup)
    else:
        if platform.system() != "Darwin":
            raise ValueError("This backup utility requires the existing native Mac installation")
        config, package = versions.canonical(args.config), versions.canonical(args.package)
        versions.read_private(config, 65536)
        value = desktop.manifest(package)
        desktop.verify(package, value)
        # Missing ownership is never interpreted as permission to create storage.
        versions.read_private(config.parent / "database-storage" / RECEIPT, 16384)
        engine = select(desktop.launch_environment())
        storage = DatabaseStorage(config.parent, config, engine, value)
        operation = args.operation or str(uuid4())
        snapshots.operation_id(operation)
        print(json.dumps({"operation_id": operation}), flush=True)
        if args.action in {"restore", "resume-restore", "abort-restore"}:
            from desktop_restoration import Restoration

            if args.action == "restore":
                if bool(args.recover_administrator) != args.admin_password_stdin:
                    raise ValueError("Named administrator recovery requires its private password on stdin")
                if args.recover_administrator:
                    password = sys.stdin.readline(2049).rstrip("\r\n")
                    from desktop_restore_authority import save

                    save(
                        config.parent,
                        operation,
                        {"username": args.recover_administrator, "password": password, "reset_mfa": True},
                    )
                owner = Restoration(
                    storage,
                    operation,
                    args.backup,
                    secrets_policy="keep_current" if args.keep_current_credentials else "review",
                    recover_admin=bool(args.recover_administrator),
                )
            else:
                owner = Restoration(storage, operation)
            if args.action == "abort-restore":
                result = owner.abort()
            else:
                result = owner.apply(
                    progress=lambda stage, done, total: print(
                        json.dumps({"stage": stage, "completed": done, "total": total}), flush=True
                    )
                )
            print(json.dumps(result, sort_keys=True), flush=True)
            return result
        backup = snapshots.Snapshot(storage, operation)
        if args.action == "export":
            result = backup.export(
                progress=lambda stage, done, total: print(
                    json.dumps({"stage": stage, "completed": done, "total": total}), flush=True
                )
            )
            result = {"status": "completed", "backup": str(backup.output), "snapshot": result}
        else:
            result = backup.cancel()
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as error:
        raise SystemExit(
            str(error) or "Backup interrupted; resume or explicitly cancel its saved UUID"
        ) from None
