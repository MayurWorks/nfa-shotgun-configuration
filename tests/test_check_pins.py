import importlib.util
import os
import subprocess

from conftest import ROOT

spec = importlib.util.spec_from_file_location("cp", ROOT / "tools" / "check_pins.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def sh(*a, cwd):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def test_detects_unpushed_commit_and_missing_tag(tmp_path):
    origin = tmp_path / "origin" / "tk-x.git"
    origin.parent.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    sh("git", "init", "-q", "-b", "main", cwd=work)
    (work / "f").write_text("1")
    sh("git", "add", "-A", cwd=work)
    sh("git", "commit", "-q", "-m", "one", cwd=work)
    pushed = sh("git", "rev-parse", "HEAD", cwd=work)
    sh("git", "tag", "rel-1", cwd=work)
    sh("git", "clone", "-q", "--bare", str(work), str(origin), cwd=tmp_path)
    (work / "f").write_text("2")
    sh("git", "commit", "-q", "-am", "two", cwd=work)
    unpushed = sh("git", "rev-parse", "HEAD", cwd=work)

    cfg = tmp_path / "cfg"
    (cfg / "env").mkdir(parents=True)
    (cfg / "core").mkdir()
    url = "file://%s" % origin
    (cfg / "env" / "a.yml").write_text(
        "a.location:\n  type: git_branch\n  branch: main\n  path: %s\n  version: %s\n"
        "b.location:\n  type: git_branch\n  branch: main\n  path: %s\n  version: %s\n"
        "c.location:\n  type: git\n  path: %s\n  version: rel-1\n"
        "d.location:\n  type: git\n  path: %s\n  version: rel-2\n" % (url, pushed, url, unpushed, url, url))

    problems = cp.check(cfg, log=lambda m: None)
    assert len(problems) == 2
    assert any(unpushed[:10] in p for p in problems)
    assert any("rel-2" in p for p in problems)


def test_unreachable_repo_is_reported_not_raised(tmp_path):
    cfg = tmp_path / "cfg"
    (cfg / "env").mkdir(parents=True)
    (cfg / "core").mkdir()
    (cfg / "env" / "a.yml").write_text(
        "a.location:\n  type: git_branch\n  branch: main\n  path: file:///nonexistent/x.git\n  version: abc\n")
    problems = cp.check(cfg, log=lambda m: None)
    assert len(problems) == 1 and "cannot clone" in problems[0]
