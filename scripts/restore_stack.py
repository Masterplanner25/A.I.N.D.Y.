"""Restore a backup from `backup_stack.py` (OFF_LAPTOP_DEPLOYMENT_SPEC §4 and §6, phase A).

    python scripts/restore_stack.py                     # test the newest backup: scratch databases, counts compared
    python scripts/restore_stack.py 20261124T031500Z    # test that one (a folder name under the root, or a path)
    python scripts/restore_stack.py latest --live --yes # replace the stack's data with it

**The test (the default) changes nothing the stack uses.** It checks each file's sha256, restores postgres into
`<db>_restore_check` and mongo into `<mongo db>_restore_check`, compares the counts against the manifest, reads the
nodus_state archive, and drops both scratch databases. A backup that has not passed this does not count (§4).

**`--live`** is the migration's restore and needs `--yes`. It refuses while `api` or `mcp` is running (stop them; the
databases stay up). It first takes a safety backup of what it replaces (labelled `before-restore`, never pruned), then:

- postgres: restores into `<db>_incoming`, checks the counts there, and only then swaps it in. The database it
  replaced is renamed `<db>_replaced_<stamp>`, not dropped; drop it once the restored stack is checked.
- mongo: checks a scratch restore first, then restores over the live database (`--drop`, per collection).
- nodus_state: empties the volume and unpacks the archive. Creates the volume, with compose's labels, if a fresh host
  has none yet.

Exit 0 when every check passed, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backup_stack as bs  # noqa: E402

CHECK = "_restore_check"
INCOMING = "_incoming"


def resolve(root: Path, which: str) -> Path:
    if which == "latest":
        whole = bs.whole_backups(root) if root.is_dir() else []
        if not whole:
            raise bs.StackError(f"no whole backups under {root}")
        return whole[-1]
    path = Path(which)
    path = path if path.is_dir() else root / which
    if not (path / bs.MANIFEST).is_file():
        raise bs.StackError(f"{path} is not a backup (no {bs.MANIFEST})")
    return path


def compare_pg(before: dict[str, int], after: dict[str, int], restored: dict[str, int]) -> tuple[list[str], list[str]]:
    """(failures, notes). A table steady during the dump must match exactly; one written to must land in range."""
    failures, notes = [], []
    for table in sorted(set(before) | set(after)):
        b, a = before.get(table), after.get(table)
        n = restored.get(table)
        if b is None or a is None:
            notes.append(f"{table}: created or dropped during the dump (restored: {n})")
            continue
        if n is None:
            failures.append(f"{table}: missing from the restore")
        elif a == b and n != b:
            failures.append(f"{table}: {n} rows restored, {b} at backup")
        elif a != b and not min(a, b) <= n <= max(a, b):
            notes.append(f"{table}: {n} rows restored, {b}→{a} during the dump (inserts and deletes both)")
    for table in sorted(set(restored) - set(before) - set(after)):
        notes.append(f"{table}: in the restore but not counted at backup")
    return failures, notes


def compare_mongo(dumped: dict[str, int], restored: dict[str, int], failed: int) -> list[str]:
    failures = [f"{c}: {restored.get(c)} documents restored, {n} dumped"
                for c, n in sorted(dumped.items()) if restored.get(c) != n]
    if failed:
        failures.append(f"{failed} documents failed to restore")
    return failures


def check_files(path: Path, manifest: dict) -> list[str]:
    failures = []
    for part in ("postgres", "mongo", "nodus_state"):
        entry = manifest.get(part)
        if entry and bs.sha256(path / entry["file"]) != entry["sha256"]:
            failures.append(f"{entry['file']}: sha256 does not match the manifest")
    return failures


# ── postgres ───────────────────────────────────────────────────────────────────────────────


def _drop(pg: str, user: str, db: str) -> None:
    bs.run(["docker", "exec", pg, "dropdb", "-U", user, "--if-exists", "--force", db], what=f"dropping {db}")


def pg_restore_into(pg: str, user: str, target: str, dump: Path) -> None:
    _drop(pg, user, target)
    bs.run(["docker", "exec", pg, "createdb", "-U", user, target], what=f"creating {target}")
    with dump.open("rb") as f:
        bs.run(["docker", "exec", "-i", pg, "pg_restore", "-U", user, "-d", target, "--no-owner", "--no-privileges",
                "--exit-on-error"], stdin=f, what=f"pg_restore into {target}")


def check_pg(pg: str, user: str, target: str, entry: dict) -> list[str]:
    restored = bs.pg_counts(pg, user, target)
    failures, notes = compare_pg(entry["counts_before"], entry["counts_after"], restored)
    for note in notes:
        bs.log(f"  note: {note}")
    heads = bs.pg_heads(pg, user, target)
    if heads != entry.get("heads", heads):
        failures.append(f"schema heads {heads} differ from the backup's {entry['heads']}")
    bs.log(f"postgres: {len(restored)} tables, {sum(restored.values()):,} rows in {target}; heads {heads}")
    return failures


# ── mongo ──────────────────────────────────────────────────────────────────────────────────


def mongo_restore_into(mongo: str, source_db: str, target: str, archive: Path) -> tuple[dict[str, int], int]:
    with archive.open("rb") as f:
        out = bs.run(["docker", "exec", "-i", mongo, "mongorestore", "--archive", "--gzip", "--drop",
                      "--nsInclude", f"{source_db}.*", "--nsFrom", f"{source_db}.*", "--nsTo", f"{target}.*"],
                     stdin=f, what=f"mongorestore into {target}")
    return bs.mongo_restored(out.stderr.decode("utf-8", "replace"), target)


def mongo_drop(mongo: str, db: str) -> None:
    # One short mongosh, run once: the pile-up in docker-compose.mongo.yml's note came from a healthcheck every 10 s.
    bs.run(["docker", "exec", mongo, "mongosh", "--quiet", "--eval", f"db.getSiblingDB('{db}').dropDatabase()"],
           what=f"dropping mongo {db}")


# ── the two modes ──────────────────────────────────────────────────────────────────────────


def test_restore(path: Path, manifest: dict, project: str) -> list[str]:
    failures = check_files(path, manifest)
    if failures:
        return failures
    bs.log("files: sha256 match the manifest")

    pg = bs.container("postgres", project)
    user, _ = bs.pg_env(pg)
    entry = manifest["postgres"]
    target = entry["database"] + CHECK
    bs.log(f"postgres: restoring into {target} ...")
    try:
        pg_restore_into(pg, user, target, path / entry["file"])
        failures += check_pg(pg, user, target, entry)
    finally:
        _drop(pg, user, target)

    if manifest.get("mongo"):
        mongo = bs.container("mongo", project)
        entry = manifest["mongo"]
        target = entry["database"] + CHECK
        bs.log(f"mongo: restoring into {target} ...")
        try:
            restored, failed = mongo_restore_into(mongo, entry["database"], target, path / entry["file"])
            failures += compare_mongo(entry["counts"], restored, failed)
            bs.log(f"mongo: {len(restored)} collections, {sum(restored.values()):,} documents in {target}")
        finally:
            mongo_drop(mongo, target)

    if manifest.get("nodus_state"):
        members = bs.tar_members(path / manifest["nodus_state"]["file"])
        if members != manifest["nodus_state"]["members"]:
            failures.append(f"nodus_state: {members} entries, manifest says {manifest['nodus_state']['members']}")
        bs.log(f"nodus_state: {members} entries readable")
    return failures


def live_restore(path: Path, manifest: dict, project: str, root: Path) -> list[str]:
    running = [s for s in ("api", "mcp") if bs.container(s, project, required=False)]
    if running:
        raise bs.StackError(f"stop {', '.join(running)} first: a live restore must not race the app's writes")

    failures = test_restore(path, manifest, project)
    if failures:
        return failures
    bs.log("the backup passed its test; taking a safety backup of what it replaces ...")
    bs.backup(root, project=project, label="before-restore")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pg = bs.container("postgres", project)
    user, live_db = bs.pg_env(pg)
    entry = manifest["postgres"]
    incoming = live_db + INCOMING
    bs.log(f"postgres: restoring into {incoming} ...")
    pg_restore_into(pg, user, incoming, path / entry["file"])
    failures = check_pg(pg, user, incoming, entry)
    if failures:
        bs.log(f"postgres: {incoming} kept for inspection; {live_db} untouched")
        return failures
    replaced = f"{live_db}_replaced_{stamp.lower()}"
    bs.psql(pg, user, "postgres", f'alter database "{live_db}" rename to "{replaced}"')
    bs.psql(pg, user, "postgres", f'alter database "{incoming}" rename to "{live_db}"')
    bs.log(f"postgres: {live_db} is the restore; the old one is {replaced} (drop it once the stack is checked)")

    if manifest.get("mongo"):
        mongo = bs.container("mongo", project)
        entry = manifest["mongo"]
        restored, failed = mongo_restore_into(mongo, entry["database"], entry["database"], path / entry["file"])
        failures += compare_mongo(entry["counts"], restored, failed)
        bs.log(f"mongo: {len(restored)} collections restored over {entry['database']}")

    if manifest.get("nodus_state"):
        vol = bs.volume("nodus_state", project)
        if vol is None:
            vol = f"{project}_nodus_state"
            bs.run(["docker", "volume", "create", "--label", f"com.docker.compose.project={project}",
                    "--label", "com.docker.compose.volume=nodus_state", vol], what="creating nodus_state")
        with (path / manifest["nodus_state"]["file"]).open("rb") as f:
            bs.run(["docker", "run", "--rm", "-i", "-v", f"{vol}:/v", "--entrypoint", "sh", bs.image_of(pg), "-c",
                    "find /v -mindepth 1 -delete && tar -C /v -xzf -"], stdin=f, what="restoring nodus_state")
        bs.log(f"nodus_state: restored into {vol}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("backup", nargs="?", default="latest", help="'latest' (default), a folder name, or a path")
    parser.add_argument("--dir", type=Path, default=None, help="backup root (default $AINDY_BACKUP_DIR or ~/aindy-backups)")
    parser.add_argument("--project", default=bs.PROJECT, help="compose project name")
    parser.add_argument("--live", action="store_true", help="replace the stack's data (needs --yes)")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.yes:
        parser.error("--live replaces the stack's data; add --yes")
    root = args.dir or bs.default_dir()
    try:
        path = resolve(root, args.backup)
        manifest = json.loads((path / bs.MANIFEST).read_text(encoding="utf-8"))
        bs.log(f"backup {path.name} (commit {manifest.get('git_sha') or '?'})")
        if args.live:
            failures = live_restore(path, manifest, args.project, root)
        else:
            failures = test_restore(path, manifest, args.project)
    except bs.StackError as exc:
        bs.log(f"RESTORE FAILED: {exc}")
        return 1
    for failure in failures:
        bs.log(f"FAIL: {failure}")
    bs.log("RESTORE OK" if not failures else f"RESTORE FAILED: {len(failures)} problems")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
