import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

spec = importlib.util.spec_from_file_location("rp", ROOT / "tools" / "repin_and_push.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def sh(*a, cwd):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def make_repo(root, name):
    origin = root / "origins" / (name + ".git")
    origin.mkdir(parents=True)
    sh("git", "init", "-q", "--bare", "-b", "main", cwd=origin)
    work = root / "NFA" / name
    work.mkdir(parents=True)
    sh("git", "init", "-q", "-b", "main", cwd=work)
    sh("git", "remote", "add", "origin", str(origin), cwd=work)
    (work / "a.txt").write_text(name)
    sh("git", "add", "-A", cwd=work)
    sh("git", "commit", "-q", "-m", "one", cwd=work)
    sh("git", "push", "-q", "-u", "origin", "main", cwd=work)
    return work


@pytest.fixture
def world(tmp_path):
    app = make_repo(tmp_path, "tk-app")
    other = make_repo(tmp_path, "tk-other")
    cfg = make_repo(tmp_path, "nfa-shotgun-configuration")
    (cfg / "env").mkdir()
    old = sh("git", "rev-parse", "HEAD", cwd=app)
    other_old = sh("git", "rev-parse", "HEAD", cwd=other)
    (cfg / "env" / "app_locations.yml").write_text(
        "# keep me\n"
        "apps.tk-app.location:\n  type: git_branch\n  branch: main\n"
        "  path: https://github.com/MayurWorks/tk-app.git\n  version: %s\n"
        "apps.tk-other.location:\n  type: git_branch\n  branch: main\n"
        "  path: https://github.com/MayurWorks/tk-other.git\n  version: %s\n"
        "apps.tk-up.location:\n  type: app_store\n  name: tk-up\n  version: v1\n" % (old, other_old))
    sh("git", "add", "-A", cwd=cfg)
    sh("git", "commit", "-q", "-m", "cfg", cwd=cfg)
    sh("git", "push", "-q", cwd=cfg)
    return tmp_path, cfg, app, other, old


def new_commit(repo):
    (repo / "b.txt").write_text(os.urandom(4).hex())
    sh("git", "add", "-A", cwd=repo)
    sh("git", "commit", "-q", "-m", "change", cwd=repo)
    return sh("git", "rev-parse", "HEAD", cwd=repo)


def test_repin_dry_run_changes_nothing(world):
    tmp, cfg, app, other, old = world
    new_commit(app)
    before = (cfg / "env" / "app_locations.yml").read_text()
    rp.repin(cfg, tmp / "NFA", apply=False, log=lambda m: None)
    assert (cfg / "env" / "app_locations.yml").read_text() == before


def test_repin_apply_updates_sha_commits_and_pushes(world):
    tmp, cfg, app, other, old = world
    sha = new_commit(app)
    rp.repin(cfg, tmp / "NFA", apply=True, log=lambda m: None)
    text = (cfg / "env" / "app_locations.yml").read_text()
    assert "version: %s" % sha in text
    assert "version: %s" % old not in text
    assert text.startswith("# keep me")
    assert "type: app_store" in text  # unrelated descriptor left alone
    assert sh("git", "status", "--porcelain", cwd=cfg) == ""
    # config and app pushed to their origins
    assert sh("git", "rev-parse", "main", cwd=tmp / "origins" / "tk-app.git") == sha
    assert "Re-pin" in sh("git", "log", "-1", "--format=%s", cwd=tmp / "origins" / "nfa-shotgun-configuration.git")


def test_repin_uses_current_branch(world):
    tmp, cfg, app, other, old = world
    sh("git", "checkout", "-q", "-b", "feature/x", cwd=app)
    new_commit(app)
    rp.repin(cfg, tmp / "NFA", apply=True, log=lambda m: None)
    assert "branch: feature/x" in (cfg / "env" / "app_locations.yml").read_text()


def test_repin_skips_dirty_repo(world):
    tmp, cfg, app, other, old = world
    new_commit(app)
    (app / "dirty.txt").write_text("x")
    plan, problems = rp.repin(cfg, tmp / "NFA", apply=True, log=lambda m: None)
    assert "tk-app" not in plan and any("uncommitted" in p for p in problems)
    assert "version: %s" % old in (cfg / "env" / "app_locations.yml").read_text()


def test_promote_tags_and_converts_to_git_descriptors(world):
    tmp, cfg, app, other, old = world
    rp.promote(cfg, tmp / "NFA", "rel-1", apply=True, log=lambda m: None)
    text = (cfg / "env" / "app_locations.yml").read_text()
    assert "git_branch" not in text
    assert text.count("type: git\n") == 2 and text.count("version: rel-1") == 2
    assert "rel-1" in sh("git", "tag", cwd=app)
    assert "rel-1" in sh("git", "tag", cwd=tmp / "origins" / "tk-app.git")


def test_promote_refuses_retag_on_other_commit(world):
    tmp, cfg, app, other, old = world
    sh("git", "tag", "rel-1", cwd=app)
    new_commit(app)
    sh("git", "tag", "-f", "rel-1", cwd=app)  # now points at a different commit than the pin
    with pytest.raises(SystemExit):
        rp.promote(cfg, tmp / "NFA", "rel-1", apply=True, log=lambda m: None)
