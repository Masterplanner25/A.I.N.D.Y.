"""Deploy a CI-built api image to this host (OFF_LAPTOP_DEPLOYMENT_SPEC §3, phase C).

    python3 scripts/deploy_stack.py <commit>          # a full sha, or any git ref this clone knows (HEAD, main, a short sha)
    python3 scripts/deploy_stack.py <commit> --no-backup
    python3 scripts/deploy_stack.py <previous commit> # a rollback is the same command

In order, stopping at the first failure:

1. **Pull** `ghcr.io/<owner>/aindy-api:<sha>` (published by `.github/workflows/publish-image.yml`). Nothing on the host
   has changed if this fails.
2. **Read the counters** (OPS-041: they reset on every recreate) and keep them in the deploy log.
3. **Back up** (`backup_stack.py`), unless `--no-backup`. A release that moves the runtime pin migrates the database
   when the api boots, and that cannot be undone except by a restore.
4. **Write `AINDY_IMAGE=<image>` into `.env`**, so every later `docker compose up` keeps this image instead of falling
   back to a local build.
5. **Recreate** `api` and `mcp` (`up -d --no-build`), and wait for the api's healthcheck (up to 10 minutes: a cold
   boot imports the 16 domains twice).
6. **Confirm:** the runtime version and where it is installed, the boot profile and plugin count, both schema heads.
   Each deploy appends one line to `~/aindy-deploys.jsonl` (`$AINDY_DEPLOY_LOG`): when, from what, to what, the counters.

**The stack keeps its mode.** A host runs either as the instance (all three profiles) or in dev mode
(`docker-compose.dev.yml` layered on, no `public-mcp`; DEPLOYMENT.md §6). The script reads the mode from the running
api and deploys in the same one, so a deploy to the server during its parallel run cannot quietly make it a second
instance. `--dev` or `--instance` changes it on purpose; with no api running, one of them is required.

The compose files come from this clone: when its HEAD is not the commit being deployed, it says so (`git checkout <sha>`
first, so compose and the image agree). Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backup_stack as bs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("docker-compose.prod.yml", "docker-compose.mongo.yml")
PROFILES = ("full", "mail", "public-mcp")
DEV_FILE = "docker-compose.dev.yml"
DEV_PROFILES = ("full", "mail")  # only the instance holds the public domain
REPOSITORY = os.environ.get("AINDY_IMAGE_REPOSITORY", "ghcr.io/masterplanner25/aindy-api")
HEALTH_TIMEOUT_S = 600
SHA = re.compile(r"^[0-9a-f]{40}$")
# The counters the adoption records read before every recreate (OPS-041). Each resets when the api restarts.
# `aindy_payload_identity_mismatch_total` has no sample line until it counts one, so "none" for it means zero.
COUNTERS = ("aindy_payload_identity_mismatch_total", "aindy_effect_gate_outcomes_total", "aindy_llm_key_source_total")


def compose(*args: str, profiles=PROFILES, dev: bool = False) -> list[str]:
    cmd = ["docker", "compose"]
    for f in COMPOSE_FILES + ((DEV_FILE,) if dev else ()):
        cmd += ["-f", str(ROOT / f)]
    for p in profiles:
        cmd += ["--profile", p]
    return cmd + list(args)


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def resolve_sha(ref: str) -> str:
    """A full sha as given; anything else through this clone's git (fetch first for a newer merge)."""
    if SHA.match(ref):
        return ref
    sha = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if not sha:
        raise bs.StackError(f"'{ref}' is not a full sha and this clone cannot resolve it (git fetch?)")
    return sha


# ── .env ───────────────────────────────────────────────────────────────────────────────────


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if m:
                values[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return values


def set_env(path: Path, key: str, value: str) -> str | None:
    """Set one key, keeping every other line, its order and its line endings. Returns the old value."""
    raw = path.read_bytes() if path.is_file() else b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    content = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.splitlines()
    old, done = None, False
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=(.*)$")
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m and not done:
            old = m.group(1).strip().strip('"').strip("'")
            lines[i] = f"{key}={value}"
            done = True
    if not done:
        lines.append(f"{key}={value}")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + (newline.join(lines) + newline).encode("utf-8"))
    return old


# ── the running api ────────────────────────────────────────────────────────────────────────


def api_url(env: dict[str, str]) -> str:
    return f"http://{env.get('AINDY_BIND_ADDR') or '127.0.0.1'}:8000"


def get(url: str, timeout: float = 10) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - our own api, by address from .env
        return resp.read().decode("utf-8", "replace")


def counters(metrics: str) -> list[str]:
    return [line for line in metrics.splitlines() if line.split("{")[0].split(" ")[0] in COUNTERS]


def health(container_id: str) -> str:
    out = bs.run(["docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                  container_id], what="reading health")
    return bs.text(out).strip()


def running_mode(container_id: str) -> str:
    """'dev' when the container runs with AINDY_ENVIRONMENT=dev, else 'instance'. Reads the env, never prints it."""
    out = bs.run(["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", container_id],
                 what="reading the api's mode")
    lines = bs.text(out).splitlines()
    return "dev" if any(line.strip().lower() == "aindy_environment=dev" for line in lines) else "instance"


def wait_healthy(timeout_s: int = HEALTH_TIMEOUT_S, project: str = bs.PROJECT) -> str:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        cid = bs.container("api", project, required=False)
        state = health(cid) if cid else "absent"
        if state != last:
            bs.log(f"api: {state}")
            last = state
        if state == "healthy":
            return cid
        if state in ("unhealthy", "exited", "dead"):
            break
        time.sleep(5)
    cid = bs.container("api", project, required=False)
    tail = bs.text(bs.run(["docker", "logs", "--tail", "30", cid], what="reading logs")) if cid else ""
    raise bs.StackError(f"the api did not become healthy (last: {last}).\n{tail}")


def confirm(cid: str, env: dict[str, str], project: str = bs.PROJECT) -> dict:
    version = bs.text(bs.run(["docker", "exec", cid, "python", "-c",
                              "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__)[0])"],
                             what="reading the runtime version")).strip()
    runtime = json.loads(get(api_url(env) + "/api/version")).get("runtime", {})
    pg = bs.container("postgres", project)
    user, db = bs.pg_env(pg)
    return {"runtime": version, "boot_profile": runtime.get("boot_profile"),
            "app_plugin_count": runtime.get("app_plugin_count"), "heads": bs.pg_heads(pg, user, db)}


# ── the deploy ─────────────────────────────────────────────────────────────────────────────


def deploy(ref: str, *, backup: bool = True, services=("api", "mcp"), profiles=None, mode: str = "keep",
           project: str = bs.PROJECT) -> dict:
    sha = resolve_sha(ref)
    current = bs.container("api", project, required=False)
    running = running_mode(current) if current else None
    if mode == "keep":
        if not running:
            raise bs.StackError("no api is running, so there is no mode to keep: say --dev or --instance")
        mode = running
    elif running and running != mode:
        bs.log(f"MODE CHANGE: the running api is {running}; this deploy makes it {mode}")
    dev = mode == "dev"
    if profiles is None:
        profiles = DEV_PROFILES if dev else PROFILES
    if dev and "public-mcp" in profiles:
        raise bs.StackError("a dev stack never runs public-mcp: only the instance holds the public domain")
    bs.log(f"mode: {mode}")
    image = f"{REPOSITORY}:{sha}"
    env_path = ROOT / ".env"
    env = read_env(env_path)
    head = git("rev-parse", "HEAD")
    if head and head != sha:
        bs.log(f"note: compose files are from {head[:12]}, the image from {sha[:12]} (git checkout {sha[:12]} to match)")

    bs.log(f"pulling {image} ...")
    bs.run(["docker", "pull", image], what=f"pulling {image}")

    previous = bs.image_of(current) if current else None
    read = []
    if current:
        try:
            read = counters(get(api_url(env) + "/metrics/"))
        except OSError as exc:
            bs.log(f"counters: could not read /metrics/ ({exc}); continuing")
        bs.log("counters: " + ("; ".join(read) if read else "none reported"))

    if backup:
        bs.log("backing up before the recreate ...")
        bs.backup(bs.default_dir(), project=project)

    old = set_env(env_path, "AINDY_IMAGE", image)
    bs.log(f".env: AINDY_IMAGE={image} (was {old or 'unset: local build'})")

    bs.log(f"recreating {', '.join(services)} ...")
    bs.run(compose("up", "-d", "--no-build", *services, profiles=profiles, dev=dev), what="docker compose up")
    cid = wait_healthy(project=project)
    came_up = running_mode(cid)
    if came_up != mode:
        raise bs.StackError(f"the api came up as {came_up}, not {mode}: stop it and check the compose files")
    result = confirm(cid, read_env(env_path), project)
    bs.log(f"confirm: runtime {result['runtime']}; {result['boot_profile']}, {result['app_plugin_count']} plugins; "
           f"heads {result['heads']}")

    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sha": sha, "image": image,
              "previous_image": previous, "mode": mode, "counters": read, **result}
    log_path = Path(os.environ.get("AINDY_DEPLOY_LOG") or Path.home() / "aindy-deploys.jsonl")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    if previous and previous.startswith(REPOSITORY + ":"):
        bs.log(f"rollback: python3 scripts/deploy_stack.py {previous.rsplit(':', 1)[1]}")
    elif previous:
        bs.log(f"rollback: remove AINDY_IMAGE from .env (the previous image was {previous}), then up -d api mcp")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("commit", help="full sha, or a git ref this clone can resolve")
    parser.add_argument("--no-backup", action="store_true", help="skip the backup before the recreate")
    parser.add_argument("--services", default="api,mcp", help="services to recreate (default api,mcp)")
    parser.add_argument("--profiles", default=None,
                        help="compose profiles (default: all three for the instance, full,mail in dev mode)")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--dev", dest="mode", action="store_const", const="dev",
                       help="deploy in dev mode (docker-compose.dev.yml, no public-mcp)")
    which.add_argument("--instance", dest="mode", action="store_const", const="instance",
                       help="deploy as the instance: only ever on the one host that is it")
    parser.add_argument("--project", default=bs.PROJECT)
    args = parser.parse_args(argv)
    try:
        deploy(args.commit, backup=not args.no_backup, services=tuple(filter(None, args.services.split(","))),
               profiles=tuple(filter(None, args.profiles.split(","))) if args.profiles else None,
               mode=args.mode or "keep", project=args.project)
    except bs.StackError as exc:
        bs.log(f"DEPLOY FAILED: {exc}")
        return 1
    bs.log("DEPLOY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
