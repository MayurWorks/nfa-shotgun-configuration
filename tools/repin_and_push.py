#!/usr/bin/env python3
"""
Re-pin the config to your latest repo commits and push everything in one run,
and promote a tested dev state to production.

  repin    for every MayurWorks repo checked out under --repos-dir that the
           config pins with a git_branch descriptor: push the repo, then set the
           descriptor's `version:` to that repo's HEAD (and `branch:` to the
           branch it is on), commit and push the config.
  promote  tag each pinned commit (--tag) in its repo, push the tags, and turn
           the config's git_branch descriptors into `type: git` pinned to that
           tag. Run this on a production branch of the config, never on dev.

Both default to a DRY RUN. Add --apply to really commit / tag / push.

  python tools/repin_and_push.py repin   --repos-dir ~/NFA
  python tools/repin_and_push.py repin   --repos-dir ~/NFA --apply --run-tests
  python tools/repin_and_push.py promote --repos-dir ~/NFA --tag rel-2026.10.13 --apply
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("od", HERE / "offline_descriptors.py")
od = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(od)


def run(*args, cwd=None, check=True):
    return subprocess.run(list(args), cwd=cwd, check=check, capture_output=True, text=True)


def git(repo, *args, check=True):
    return run("git", *args, cwd=str(repo), check=check)


def head_sha(repo):
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def current_branch(repo):
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def is_clean(repo):
    return git(repo, "status", "--porcelain").stdout.strip() == ""


def pinned_blocks(config_root: Path):
    """git_branch descriptor blocks keyed by repo name."""
    out = {}
    for b in od.collect(config_root):
        if b.type == "git_branch":
            out.setdefault(od.repo_name_from_path(b.fields["path"]), []).append(b)
    return out


def set_fields(block, **changes):
    fields = dict(block.fields)
    fields.update(changes)
    return od.render(block, fields)


def rewrite_blocks(config_root: Path, edit):
    """Apply edit(block) -> new fields dict (or None to leave) to every
    descriptor block; returns number changed."""
    changed = 0
    for f in od.config_files(config_root):
        lines = f.read_text().split("\n")
        blocks = od.find_blocks(f, lines)
        touched = False
        for b in reversed(blocks):
            new = edit(b)
            if new is None or new == b.fields:
                continue
            lines[b.start:b.end] = od.render(b, new)
            changed += 1
            touched = True
        if touched:
            f.write_text("\n".join(lines))
    return changed


# ---------------------------------------------------------------------- repin
def repin(config_root, repos_dir, apply=False, run_tests=False, log=print):
    pins = pinned_blocks(config_root)
    plan, problems = {}, []
    for name in sorted(pins):
        repo = Path(repos_dir) / name
        if not (repo / ".git").exists():
            continue
        if not is_clean(repo):
            problems.append("%s has uncommitted changes" % name)
            continue
        if run_tests and (repo / "tests").is_dir():
            r = run(sys.executable, "-m", "pytest", "-q", "tests", cwd=str(repo), check=False)
            if r.returncode != 0:
                problems.append("%s: tests failed\n%s" % (name, r.stdout[-400:]))
                continue
        plan[name] = (head_sha(repo), current_branch(repo))

    for p in problems:
        log("SKIP/FAIL " + p)
    if problems:
        log("fix the above (nothing pinned for those repos) and re-run")

    for name, (sha, branch) in plan.items():
        old = pins[name][0].fields
        log("%-28s %s@%s -> %s@%s" % (name, old.get("branch"), old["version"][:8], branch, sha[:8]))

    if not apply:
        log("\ndry run, nothing changed (use --apply)")
        return plan, problems

    for name in plan:
        git(Path(repos_dir) / name, "push", "-u", "origin", "HEAD")

    def edit(block):
        if block.type != "git_branch":
            return None
        name = od.repo_name_from_path(block.fields["path"])
        if name not in plan:
            return None
        sha, branch = plan[name]
        return dict(block.fields, version=sha, branch=branch)

    n = rewrite_blocks(config_root, edit)
    if n:
        git(config_root, "add", "-A")
        msg = "Re-pin %s\n\n%s" % (", ".join(sorted(plan)), "\n".join(
            "%s %s" % (k, v[0][:8]) for k, v in sorted(plan.items())))
        git(config_root, "commit", "-m", msg)
        git(config_root, "push", "-u", "origin", "HEAD")
        log("re-pinned %d descriptor(s), config committed and pushed" % n)
    else:
        log("nothing to change in the config")
    return plan, problems


# -------------------------------------------------------------------- promote
def promote(config_root, repos_dir, tag, apply=False, log=print):
    pins = pinned_blocks(config_root)
    for name, blocks in sorted(pins.items()):
        sha = blocks[0].fields["version"]
        log("%-28s tag %s at %s" % (name, tag, sha[:8]))
    if not apply:
        log("\ndry run, nothing changed (use --apply)")
        return pins

    for name, blocks in pins.items():
        repo = Path(repos_dir) / name
        if not (repo / ".git").exists():
            raise SystemExit("%s is not checked out under %s" % (name, repos_dir))
        sha = blocks[0].fields["version"]
        have = git(repo, "rev-parse", "-q", "--verify", "refs/tags/%s" % tag, check=False).stdout.strip()
        if have and git(repo, "rev-parse", "%s^{commit}" % tag).stdout.strip() != sha:
            raise SystemExit("%s: tag %s already exists on a different commit" % (name, tag))
        if not have:
            git(repo, "tag", tag, sha)
        git(repo, "push", "origin", "refs/tags/%s" % tag)

    def edit(block):
        if block.type != "git_branch":
            return None
        return {"type": "git", "path": block.fields["path"], "version": tag}

    n = rewrite_blocks(config_root, edit)
    git(config_root, "add", "-A")
    git(config_root, "commit", "-m", "Promote to production: %s\n\nAll MayurWorks apps pinned to tag %s." % (tag, tag))
    log("promoted %d descriptor(s) to tag %s; push the config branch yourself after review" % (n, tag))
    return pins


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("repin", "promote"))
    ap.add_argument("--config", default=str(HERE.parent), help="config repo (default: this one)")
    ap.add_argument("--repos-dir", required=True, help="folder containing your repo clones, e.g. ~/NFA")
    ap.add_argument("--tag")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--run-tests", action="store_true")
    a = ap.parse_args(argv)
    cfg, repos = Path(a.config), Path(a.repos_dir).expanduser()
    if a.command == "repin":
        _, problems = repin(cfg, repos, a.apply, a.run_tests)
        return 1 if problems else 0
    if not a.tag:
        ap.error("promote needs --tag")
    promote(cfg, repos, a.tag, a.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
