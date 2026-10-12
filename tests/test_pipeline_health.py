import json
import os

from conftest import HOOKS, load_module

ph = load_module("pipeline_health", HOOKS / "pipeline_health.py")


def test_writes_jsonl(tmp_path):
    path = ph.log_event("publish_validate", directory=str(tmp_path), errors=2)
    rec = json.loads(open(path).readline())
    assert rec["event"] == "publish_validate" and rec["errors"] == 2
    assert rec["host"] and "ts" in rec


def test_appends_one_line_per_event(tmp_path):
    ph.log_event("a", directory=str(tmp_path))
    ph.log_event("b", directory=str(tmp_path))
    path = ph.log_event("a", directory=str(tmp_path))
    assert len(open(path).read().splitlines()) == 3


def test_noop_without_directory(monkeypatch):
    monkeypatch.delenv(ph.ENV_DIR, raising=False)
    assert ph.log_event("x") is None


def test_env_directory(monkeypatch, tmp_path):
    monkeypatch.setenv(ph.ENV_DIR, str(tmp_path / "logs"))
    assert ph.log_event("x") is not None
    assert os.listdir(tmp_path / "logs")


def test_never_raises_on_unwritable_dir(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert ph.log_event("x", directory=str(blocker / "sub")) is None


def test_non_serialisable_values_are_stringified(tmp_path):
    path = ph.log_event("x", directory=str(tmp_path), obj=object())
    assert json.loads(open(path).readline())["event"] == "x"


def test_summarise_day(tmp_path):
    ph.log_event("publish_validate", directory=str(tmp_path))
    ph.log_event("publish_validate", directory=str(tmp_path))
    ph.log_event("publish_finalize", directory=str(tmp_path))
    assert ph.summarise_day(str(tmp_path)) == {"publish_validate": 2, "publish_finalize": 1}
