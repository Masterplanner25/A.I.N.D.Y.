"""OFF_LAPTOP_DEPLOYMENT_SPEC phase A: `scripts/backup_stack.py` and `scripts/restore_stack.py`.

The docker steps were proven against the live stack and a throwaway one (2026-11-25); these cover what decides
whether a restore passes, what gets pruned, and what the live restore refuses.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.app_profile

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import backup_stack as bs  # noqa: E402
import restore_stack as rs  # noqa: E402

# ── what passes ────────────────────────────────────────────────────────────────────────────


def test_a_steady_table_must_restore_exactly():
    failures, _ = rs.compare_pg({"tasks": 10}, {"tasks": 10}, {"tasks": 9})
    assert failures == ["tasks: 9 rows restored, 10 at backup"]
    assert rs.compare_pg({"tasks": 10}, {"tasks": 10}, {"tasks": 10}) == ([], [])


def test_a_table_written_during_the_dump_lands_between_its_two_counts():
    # The live case of 2026-11-25: request_metrics 562,558 -> 562,561 during the dump, 562,558 restored.
    assert rs.compare_pg({"request_metrics": 562558}, {"request_metrics": 562561},
                         {"request_metrics": 562558}) == ([], [])
    failures, notes = rs.compare_pg({"m": 5}, {"m": 8}, {"m": 2})
    assert failures == [] and notes, "out of range on a moving table is noted, not failed: deletes happen too"


def test_a_missing_table_fails_and_a_new_one_is_only_noted():
    failures, notes = rs.compare_pg({"a": 1, "b": 2}, {"a": 1, "b": 2}, {"a": 1, "c": 0})
    assert failures == ["b: missing from the restore"]
    assert notes == ["c: in the restore but not counted at backup"]


def test_mongo_must_restore_every_document_it_dumped():
    assert rs.compare_mongo({"posts": 2, "social_metrics_history": 14},
                            {"posts": 2, "social_metrics_history": 14}, 0) == []
    assert rs.compare_mongo({"posts": 2}, {"posts": 1}, 1) == ["posts: 1 documents restored, 2 dumped",
                                                               "1 documents failed to restore"]


def test_mongo_counts_come_from_the_tools_own_log():
    dumped = ("2026-11-25T04:06:40.1+0000\twriting aindy_default.posts to archive on stdout\n"
              "2026-11-25T04:06:40.2+0000\tdone dumping aindy_default.posts (2 documents)\n"
              "2026-11-25T04:06:40.2+0000\tdone dumping aindy_default.social_metrics_history (14 documents)\n"
              "2026-11-25T04:06:40.2+0000\tdone dumping other.x (1 document)\n")
    assert bs.mongo_dumped(dumped, "aindy_default") == {"posts": 2, "social_metrics_history": 14}
    restored = ("2026-11-25T04:08:01.0+0000\tfinished restoring aindy_default_restore_check.posts "
                "(2 documents, 0 failures)\n")
    assert bs.mongo_restored(restored, "aindy_default_restore_check") == ({"posts": 2}, 0)


def test_the_social_database_is_the_runtimes_name_not_the_urls(monkeypatch):
    # AINDY/db/mongo_setup.py reads MONGO_DB_NAME (default aindy_default); compose's URL path names an empty one.
    import importlib

    monkeypatch.delenv("MONGO_DB_NAME", raising=False)
    assert importlib.reload(bs).MONGO_DB == "aindy_default"


def test_psql_counts_parse():
    assert bs.parse_counts("tasks\t3\nusers\t4\n\n") == {"tasks": 3, "users": 4}


def test_a_changed_file_fails_before_anything_is_restored(tmp_path):
    (tmp_path / "postgres.dump").write_bytes(b"dump")
    manifest = {"postgres": {"file": "postgres.dump", "sha256": bs.sha256(tmp_path / "postgres.dump")},
                "mongo": None, "nodus_state": None}
    assert rs.check_files(tmp_path, manifest) == []
    (tmp_path / "postgres.dump").write_bytes(b"dumq")
    assert rs.check_files(tmp_path, manifest) == ["postgres.dump: sha256 does not match the manifest"]


# ── what is kept ───────────────────────────────────────────────────────────────────────────


def _backups(root: Path, *names: str) -> None:
    for name in names:
        (root / name).mkdir()
        if not name.endswith(".partial"):
            (root / name / bs.MANIFEST).write_text("{}", encoding="utf-8")


def test_prune_keeps_the_newest_whole_backups_and_never_a_labelled_one(tmp_path):
    days = [f"202611{d:02d}T031500Z" for d in range(1, 18)]
    _backups(tmp_path, *days, "20261101T000000Z-before-restore")
    gone = bs.prune(tmp_path, 14)
    assert [p.name for p in gone] == days[:3]
    assert [p.name for p in bs.whole_backups(tmp_path)] == days[3:]
    assert (tmp_path / "20261101T000000Z-before-restore").is_dir()


def test_prune_clears_a_failed_partial_but_not_one_still_running(tmp_path):
    _backups(tmp_path, "20261110T031500Z.partial", "20261111T031500Z", "20261112T031500Z.partial")
    gone = bs.prune(tmp_path, 14)
    assert [p.name for p in gone] == ["20261110T031500Z.partial"]
    assert (tmp_path / "20261112T031500Z.partial").is_dir()


def test_latest_is_the_newest_whole_backup(tmp_path):
    _backups(tmp_path, "20261110T031500Z", "20261111T031500Z", "20261112T031500Z.partial",
             "20261113T000000Z-before-restore")
    assert rs.resolve(tmp_path, "latest").name == "20261111T031500Z"
    assert rs.resolve(tmp_path, "20261110T031500Z").name == "20261110T031500Z"
    with pytest.raises(bs.StackError, match="not a backup"):
        rs.resolve(tmp_path, "20261112T031500Z.partial")


# ── what the live restore refuses ──────────────────────────────────────────────────────────


def test_live_needs_yes(capsys):
    with pytest.raises(SystemExit):
        rs.main(["--live"])
    assert "--yes" in capsys.readouterr().err


def test_live_refuses_while_the_app_is_running(tmp_path, monkeypatch):
    _backups(tmp_path, "20261111T031500Z")
    monkeypatch.setattr(bs, "container", lambda service, project=bs.PROJECT, required=True:
                        "cid" if service in ("api", "postgres") else None)
    monkeypatch.setattr(rs, "test_restore", lambda *a: pytest.fail("nothing is restored while the api runs"))
    assert rs.main(["--dir", str(tmp_path), "--live", "--yes"]) == 1


def test_live_stops_at_a_failed_test_before_touching_the_stack(tmp_path, monkeypatch):
    _backups(tmp_path, "20261111T031500Z")
    monkeypatch.setattr(bs, "container", lambda service, project=bs.PROJECT, required=True: None)
    monkeypatch.setattr(rs, "test_restore", lambda *a: ["tasks: 9 rows restored, 10 at backup"])
    monkeypatch.setattr(bs, "backup", lambda *a, **k: pytest.fail("no safety backup, no swap"))
    monkeypatch.setattr(rs, "pg_restore_into", lambda *a: pytest.fail("the live database is untouched"))
    assert rs.main(["--dir", str(tmp_path), "--live", "--yes"]) == 1

