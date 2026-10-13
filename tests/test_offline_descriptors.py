import importlib.util
import shutil
import subprocess

import yaml

from conftest import ROOT

spec = importlib.util.spec_from_file_location("od", ROOT / "tools" / "offline_descriptors.py")
od = importlib.util.module_from_spec(spec)
spec.loader.exec_module(od)

BASE = "git@git.studio.local:pipeline"


def copy_config(tmp_path):
    dst = tmp_path / "cfg"
    shutil.copytree(ROOT / "env", dst / "env")
    shutil.copytree(ROOT / "core", dst / "core", ignore=shutil.ignore_patterns("schema", "templates", "hooks"))
    return dst


def test_mapping_rules():
    assert od.to_mirror({"type": "app_store", "name": "tk-core", "version": "v0.23.8"}, BASE) == {
        "type": "git", "path": BASE + "/tk-core.git", "version": "v0.23.8"}
    assert od.to_mirror({"type": "github_release", "organization": "nfa-vfxim", "repository": "tk-nuke", "version": "1.2"}, BASE)[
        "path"] == BASE + "/tk-nuke.git"
    gb = od.to_mirror({"type": "git_branch", "branch": "main", "version": "abc",
                       "path": "https://github.com/MayurWorks/tk-x.git"}, BASE)
    assert gb == {"type": "git_branch", "branch": "main", "version": "abc", "path": BASE + "/tk-x.git"}


def test_upstream_urls():
    assert od.upstream_of({"type": "app_store", "name": "tk-core", "version": "v1"}) == (
        "https://github.com/shotgunsoftware/tk-core.git", "v1")
    assert od.upstream_of({"type": "github_release", "organization": "nfa-vfxim", "repository": "r", "version": "2"})[0] \
        == "https://github.com/nfa-vfxim/r.git"


def test_rewrite_real_config_leaves_nothing_remote_and_yaml_still_parses(tmp_path):
    cfg = copy_config(tmp_path)
    before = {p: p.read_text() for p in od.config_files(cfg)}
    n = od.cmd_rewrite(cfg, BASE)
    assert n == 74
    assert od.cmd_status(cfg, BASE) == []
    for p in od.config_files(cfg):
        yaml.safe_load(p.read_text())  # structure intact
    # only descriptor lines changed: every comment line is untouched
    for p, old in before.items():
        old_comments = [l for l in old.split("\n") if l.lstrip().startswith("#")]
        new_comments = [l for l in p.read_text().split("\n") if l.lstrip().startswith("#")]
        assert old_comments == new_comments, p


def test_rewrite_is_idempotent(tmp_path):
    cfg = copy_config(tmp_path)
    od.cmd_rewrite(cfg, BASE)
    snapshot = {p: p.read_text() for p in od.config_files(cfg)}
    assert od.cmd_rewrite(cfg, BASE) == 0
    assert {p: p.read_text() for p in od.config_files(cfg)} == snapshot


def test_rewritten_descriptors_are_valid_git_descriptors(tmp_path):
    cfg = copy_config(tmp_path)
    od.cmd_rewrite(cfg, BASE)
    for b in od.collect(cfg):
        f = b.fields
        assert f["type"] in ("git", "git_branch")
        assert f["path"].startswith(BASE + "/") and f["path"].endswith(".git")
        assert "version" in f
        if f["type"] == "git_branch":
            assert "branch" in f


def test_dry_run_changes_nothing(tmp_path):
    cfg = copy_config(tmp_path)
    before = {p: p.read_text() for p in od.config_files(cfg)}
    assert od.cmd_rewrite(cfg, BASE, dry_run=True) == 74
    assert {p: p.read_text() for p in od.config_files(cfg)} == before


def _git(*a, cwd=None):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(cwd or "/tmp")})


def test_sync_then_check_against_local_repos(tmp_path):
    # a tiny fake "GitHub": <up>/shotgunsoftware/tk-fake.git with tag v1.0.0
    up = tmp_path / "up" / "shotgunsoftware"
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "-q", "-b", "main", cwd=work)
    (work / "f").write_text("x")
    _git("add", "f", cwd=work)
    _git("commit", "-q", "-m", "init", cwd=work)
    _git("tag", "v1.0.0", cwd=work)
    up.mkdir(parents=True)
    _git("clone", "-q", "--bare", str(work), str(up / "tk-fake.git"))

    cfg = tmp_path / "cfg"
    (cfg / "env").mkdir(parents=True)
    (cfg / "core").mkdir()
    (cfg / "env" / "a.yml").write_text(
        "apps.tk-fake.location:\n  type: app_store\n  name: tk-fake\n  version: v1.0.0\n"
        "apps.tk-other.location:\n  type: app_store\n  name: tk-fake\n  version: v9.9.9\n")

    mirror = "file://" + str(tmp_path / "mirror")
    od.cmd_sync(cfg, mirror, tmp_path / "cache", upstream_base="file://" + str(tmp_path / "up"))
    od.cmd_rewrite(cfg, mirror)
    problems = od.cmd_check(cfg, mirror)
    # v1.0.0 exists on the mirror, v9.9.9 does not
    assert len(problems) == 1 and "v9.9.9" in problems[0]
