"""Back up the stack's data: postgres, mongo and the nodus_state volume (OFF_LAPTOP_DEPLOYMENT_SPEC §4, phase A).

    python scripts/backup_stack.py                 # into $AINDY_BACKUP_DIR, else ~/aindy-backups
    python scripts/backup_stack.py --dir D --keep 14

Each run writes one folder, named for the UTC time it started:

    20261124T031500Z/
      postgres.dump        pg_dump custom format of the app database (runtime and app schema, both heads)
      mongo.archive.gz     mongodump of the social database, when mongo is running
      nodus_state.tar.gz   the nodus_state volume
      manifest.json        when, from which commit, each file's sha256, and the counts the restore checks against

It writes into `<stamp>.partial` and renames only when everything succeeded, so a folder without the suffix is a
whole backup. Then it keeps the newest `--keep` whole backups and deletes older ones and any leftover partials.

The stack keeps running. Postgres row counts are read before and after the dump: a table whose count did not move
must restore to exactly that count, and one that moved (it was written to during the dump) to a count between the two.

`restore_stack.py` restores one, into scratch databases by default (the test), or over the stack with `--live`.

Stdlib only, so a server runs it with its system python3. It reaches the databases with `docker exec`, finding the
containers by their compose labels, so it needs neither the compose files nor `.env`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "aindy-apps-monolith")
# The runtime's name for the social database (`AINDY/db/mongo_setup.py`: MONGO_DB_NAME, default "aindy_default").
# Not the path in MONGO_URL: compose's `mongodb://mongo:27017/aindy` names a database nothing writes to.
MONGO_DB = os.environ.get("MONGO_DB_NAME", "aindy_default")
KEEP = 14
STAMP = re.compile(r"^\d{8}T\d{6}Z$")

PG_FILE = "postgres.dump"
MONGO_FILE = "mongo.archive.gz"
NODUS_FILE = "nodus_state.tar.gz"
MANIFEST = "manifest.json"

# Every table in public, counted exactly, in one statement.
COUNTS_SQL = (
    "select table_name, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from public.%I', "
    "table_name), false, true, '')))[1]::text from information_schema.tables "
    "where table_schema = 'public' and table_type = 'BASE TABLE' order by 1"
)


class StackError(RuntimeError):
    """A step failed; the message says which and why."""


def default_dir() -> Path:
    return Path(os.environ.get("AINDY_BACKUP_DIR") or Path.home() / "aindy-backups")


def log(message: str) -> None:
    print(message, flush=True)


def run(cmd: list[str], *, stdin=None, stdout=None, what: str) -> subprocess.CompletedProcess:
    """Run a command; on a non-zero exit raise with its stderr. stdout is captured unless a file is given."""
    out = subprocess.run(cmd, stdin=stdin, stdout=stdout if stdout is not None else subprocess.PIPE,
                         stderr=subprocess.PIPE)
    if out.returncode != 0:
        err = out.stderr.decode("utf-8", "replace").strip()
        raise StackError(f"{what} failed (exit {out.returncode}): {err[-2000:]}")
    return out


def text(out: subprocess.CompletedProcess) -> str:
    return out.stdout.decode("utf-8", "replace")


# ── finding the stack ──────────────────────────────────────────────────────────────────────


def container(service: str, project: str = PROJECT, *, required: bool = True) -> str | None:
    """The running container of a compose service, by label: no compose file, profile or name needed."""
    out = run(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}",
               "--filter", f"label=com.docker.compose.service={service}"], what=f"finding {service}")
    ids = text(out).split()
    if not ids:
        if required:
            raise StackError(f"no running '{service}' container in compose project '{project}'")
        return None
    return ids[0]


def volume(name: str, project: str = PROJECT) -> str | None:
    out = run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}",
               "--filter", f"label=com.docker.compose.volume={name}"], what=f"finding volume {name}")
    names = text(out).split()
    return names[0] if names else None


def image_of(container_id: str) -> str:
    """An image already on the host with sh and tar in it, so the volume steps never pull one."""
    return text(run(["docker", "inspect", "-f", "{{.Config.Image}}", container_id], what="reading an image")).strip()


def pg_env(pg: str) -> tuple[str, str]:
    """The database user and name, from the postgres container's own environment."""
    env = text(run(["docker", "exec", pg, "printenv", "POSTGRES_USER", "POSTGRES_DB"], what="reading postgres env"))
    user, db = (env.split() + ["aindy", "aindy"])[:2]
    return user, db


def psql(pg: str, user: str, db: str, sql: str) -> str:
    return text(run(["docker", "exec", pg, "psql", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-AtF", "\t",
                     "-c", sql], what=f"psql on {db}"))


# ── what the restore checks against ────────────────────────────────────────────────────────


def parse_counts(rows: str) -> dict[str, int]:
    counts = {}
    for line in rows.splitlines():
        if line.strip():
            table, n = line.split("\t")
            counts[table] = int(n)
    return counts


def pg_counts(pg: str, user: str, db: str) -> dict[str, int]:
    return parse_counts(psql(pg, user, db, COUNTS_SQL))


def pg_heads(pg: str, user: str, db: str) -> dict[str, str | None]:
    heads = {}
    for table in ("alembic_version", "alembic_version_runtime"):
        try:
            heads[table] = psql(pg, user, db, f"select version_num from {table}").strip() or None
        except StackError:
            heads[table] = None
    return heads


# mongo-tools 100.20 quotes the namespace in backticks; 100.15 did not. Both are read.
_DUMPED = re.compile(r"done dumping `?([^\s`]+)`? \((\d+) documents?\)")
_RESTORED = re.compile(r"finished restoring `?([^\s`]+)`? \((\d+) documents?, (\d+) failures?\)")


def mongo_dumped(stderr: str, db: str) -> dict[str, int]:
    """Collections and their documents, from mongodump's own log (no mongosh: OPS note in docker-compose.mongo.yml)."""
    prefix = db + "."
    return {ns[len(prefix):]: int(n) for ns, n in _DUMPED.findall(stderr) if ns.startswith(prefix)}


def mongo_restored(stderr: str, db: str) -> tuple[dict[str, int], int]:
    prefix = db + "."
    counts, failures = {}, 0
    for ns, n, failed in _RESTORED.findall(stderr):
        if ns.startswith(prefix):
            counts[ns[len(prefix):]] = int(n)
            failures += int(failed)
    return counts, failures


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tar_members(path: Path) -> int:
    with tarfile.open(path, "r:gz") as tar:
        return sum(1 for _ in tar)


def git_sha() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
                             capture_output=True, text=True)
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _file(path: Path) -> dict:
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}


# ── the backup ─────────────────────────────────────────────────────────────────────────────


def backup(root: Path, *, project: str = PROJECT, mongo_db: str = MONGO_DB, keep: int = KEEP,
           label: str = "") -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = stamp + (f"-{label}" if label else "")
    work = root / f"{name}.partial"
    work.mkdir(parents=True)
    manifest: dict = {"created_at": stamp, "project": project, "git_sha": git_sha()}

    pg = container("postgres", project)
    user, db = pg_env(pg)
    log(f"postgres: counting {db} ...")
    before = pg_counts(pg, user, db)
    log(f"postgres: dumping {db} ({len(before)} tables) ...")
    with (work / PG_FILE).open("wb") as f:
        run(["docker", "exec", pg, "pg_dump", "-U", user, "-d", db, "-Fc"], stdout=f, what="pg_dump")
    after = pg_counts(pg, user, db)
    manifest["postgres"] = {**_file(work / PG_FILE), "database": db, "heads": pg_heads(pg, user, db),
                            "counts_before": before, "counts_after": after}
    moved = sorted(t for t in before if after.get(t) != before[t])
    log(f"postgres: {manifest['postgres']['bytes']:,} bytes; {len(moved)} tables written to during the dump")

    mongo = container("mongo", project, required=False)
    if mongo is None:
        log("mongo: not running, skipped")
        manifest["mongo"] = None
    else:
        log(f"mongo: dumping {mongo_db} ...")
        with (work / MONGO_FILE).open("wb") as f:
            out = run(["docker", "exec", mongo, "mongodump", "--db", mongo_db, "--archive", "--gzip"],
                      stdout=f, what="mongodump")
        counts = mongo_dumped(out.stderr.decode("utf-8", "replace"), mongo_db)
        manifest["mongo"] = {**_file(work / MONGO_FILE), "database": mongo_db, "counts": counts}
        log(f"mongo: {len(counts)} collections, {sum(counts.values()):,} documents")

    vol = volume("nodus_state", project)
    if vol is None:
        log("nodus_state: no volume, skipped")
        manifest["nodus_state"] = None
    else:
        with (work / NODUS_FILE).open("wb") as f:
            run(["docker", "run", "--rm", "-v", f"{vol}:/v:ro", "--entrypoint", "tar", image_of(pg),
                 "-C", "/v", "-czf", "-", "."], stdout=f, what="archiving nodus_state")
        manifest["nodus_state"] = {**_file(work / NODUS_FILE), "volume": vol,
                                   "members": tar_members(work / NODUS_FILE)}
        log(f"nodus_state: {manifest['nodus_state']['members']} entries")

    (work / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    final = root / name
    work.rename(final)
    log(f"backup written: {final}")
    if not label:
        for old in prune(root, keep):
            log(f"pruned: {old.name}")
    return final


def whole_backups(root: Path) -> list[Path]:
    """Scheduled backups, oldest first. Labelled ones (a restore's safety copy) are never pruned."""
    return sorted(p for p in root.iterdir() if p.is_dir() and STAMP.match(p.name))


def prune(root: Path, keep: int) -> list[Path]:
    gone = []
    whole = whole_backups(root)
    for old in whole[:-keep] if keep > 0 else []:
        shutil.rmtree(old)
        gone.append(old)
    newest = whole[-1].name if whole else ""
    for partial in root.glob("*.partial"):
        # A partial older than the newest whole backup is a failed run; a newer one may still be running.
        if partial.is_dir() and partial.name.split(".")[0] < newest:
            shutil.rmtree(partial)
            gone.append(partial)
    return gone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", type=Path, default=None, help="backup root (default $AINDY_BACKUP_DIR or ~/aindy-backups)")
    parser.add_argument("--keep", type=int, default=KEEP, help=f"whole backups to keep (default {KEEP})")
    parser.add_argument("--project", default=PROJECT, help="compose project name")
    parser.add_argument("--mongo-db", default=MONGO_DB)
    args = parser.parse_args(argv)
    try:
        backup(args.dir or default_dir(), project=args.project, mongo_db=args.mongo_db, keep=args.keep)
    except StackError as exc:
        log(f"BACKUP FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
