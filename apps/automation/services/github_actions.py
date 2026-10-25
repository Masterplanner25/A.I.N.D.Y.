"""The four GitHub Actions reads the release watcher needs (`RELEASE_HANDOFF_SPEC.md` §4), and the one
write that approves or rejects the gate (§7.3, phase 3).

The reads use a fine-grained token scoped to the repository with **Actions: read** (decision 2), from
`AINDY_GITHUB_TOKEN` in the environment and never from the repository. The write uses a second token,
`AINDY_GITHUB_APPROVE_TOKEN` (Deployments: write), sent on nothing else, so the token used every minute
cannot publish. Every call goes through the runtime's external-call wrapper, so it is counted and timed
like the drafter's and the Resolution Check's.
"""
from __future__ import annotations

import os
from typing import Any

import requests

API_ROOT = "https://api.github.com"
TOKEN_ENV = "AINDY_GITHUB_TOKEN"
APPROVE_TOKEN_ENV = "AINDY_GITHUB_APPROVE_TOKEN"
WORKFLOW_FILE = "publish.yml"
TIMEOUT_SECONDS = 20


class GitHubUnavailable(RuntimeError):
    """GitHub could not be read this tick. The watcher tries again next minute; nothing is lost."""


def token() -> str:
    return (os.getenv(TOKEN_ENV) or "").strip()


def approve_token() -> str:
    """Unset turns phase 3 off: no buttons, no reply instructions. Revoking it is the off switch."""
    return (os.getenv(APPROVE_TOKEN_ENV) or "").strip()


def _headers(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class GitHubActions:
    def __init__(self, *, db=None, user_id=None, session: Any = None):
        self.db = db
        self.user_id = user_id
        self.http = session or requests

    def _get(self, path: str, params: dict | None = None) -> Any:
        from AINDY.platform_layer.external_call_service import perform_external_call

        key = token()
        if not key:
            raise GitHubUnavailable(f"{TOKEN_ENV} is not set; the release watcher cannot read GitHub.")
        url = f"{API_ROOT}{path}"
        try:
            response = perform_external_call(
                service_name="github",
                endpoint=url,
                method="GET",
                db=self.db,
                user_id=self.user_id,
                extra={"purpose": "release_handoff"},
                operation=lambda: self.http.get(url, params=params, headers=_headers(key), timeout=TIMEOUT_SECONDS),
            )
        except requests.RequestException as exc:
            raise GitHubUnavailable(f"Could not reach GitHub: {exc}") from exc
        if response.status_code in (401, 403):
            raise GitHubUnavailable(f"GitHub refused the token ({response.status_code}) for {path}.")
        if response.status_code >= 400:
            raise GitHubUnavailable(f"GitHub returned HTTP {response.status_code} for {path}.")
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubUnavailable(f"GitHub returned a non-JSON body for {path}.") from exc

    def find_run(self, repo: str, tag: str) -> dict | None:
        """The tag's `publish.yml` run. A tag push records the tag as the run's `head_branch`."""
        body = self._get(f"/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs",
                         {"branch": tag, "event": "push", "per_page": 5})
        runs = [r for r in (body or {}).get("workflow_runs") or [] if r.get("head_branch") == tag]
        # The newest, should the tag have been pushed twice.
        return max(runs, key=lambda r: r.get("created_at") or "") if runs else None

    def jobs(self, repo: str, run_id: str) -> list[dict]:
        return list((self._get(f"/repos/{repo}/actions/runs/{run_id}/jobs", {"per_page": 50}) or {}).get("jobs") or [])

    def pending_deployments(self, repo: str, run_id: str) -> list[dict]:
        return list(self._get(f"/repos/{repo}/actions/runs/{run_id}/pending_deployments") or [])

    def approvals(self, repo: str, run_id: str) -> list[dict]:
        return list(self._get(f"/repos/{repo}/actions/runs/{run_id}/approvals") or [])

    def get_run(self, repo: str, run_id: str) -> dict:
        return self._get(f"/repos/{repo}/actions/runs/{run_id}") or {}

    def review(self, repo: str, run_id: str, environment_ids: list[int], state: str, comment: str) -> list[dict]:
        """Approve or reject the run's pending deployments, as the approve token's owner. One attempt,
        never retried: a second POST for a gate already decided is GitHub's to refuse, not ours to send."""
        from AINDY.platform_layer.external_call_service import perform_external_call

        key = approve_token()
        if not key:
            raise GitHubUnavailable(f"{APPROVE_TOKEN_ENV} is not set; A.I.N.D.Y. cannot decide the gate.")
        path = f"/repos/{repo}/actions/runs/{run_id}/pending_deployments"
        url = f"{API_ROOT}{path}"
        body = {"environment_ids": list(environment_ids), "state": state, "comment": comment}
        try:
            response = perform_external_call(
                service_name="github",
                endpoint=url,
                method="POST",
                db=self.db,
                user_id=self.user_id,
                extra={"purpose": "release_handoff_review", "state": state},
                operation=lambda: self.http.post(url, json=body, headers=_headers(key), timeout=TIMEOUT_SECONDS),
            )
        except requests.RequestException as exc:
            raise GitHubUnavailable(f"Could not reach GitHub: {exc}") from exc
        if response.status_code in (401, 403):
            raise GitHubUnavailable(f"GitHub refused the approve token ({response.status_code}) for {path}.")
        if response.status_code >= 400:
            raise GitHubUnavailable(f"GitHub returned HTTP {response.status_code} for {path}.")
        try:
            return list(response.json() or [])
        except ValueError:
            return []
