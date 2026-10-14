#!/usr/bin/env python3
"""
Fail if a pinned descriptor cannot actually be installed.

For every git_branch descriptor: the repo is reachable and the pinned commit
exists on the remote. For every `type: git` descriptor: the tag exists.
A commit that was never pushed is the classic way to break every artist's
launch, and this catches it before they see it.

    python tools/check_pins.py            # check the config in this repo
    python tools/check_pins.py --root X   # another checkout

Exit code 0 = all pins resolvable, 1 = something is broken.
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("od", HERE / "offline_descriptors.py")
od = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(od)


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def commit_exists(url: str, sha: str, workdir: Path) -> bool:
    """True if ``sha`` is present in ``url``. Uses a blobless, checkout-less
    clone so even large repos are cheap."""
    target = workdir / (od.repo_name_from_path(url) + ".git")
    if not target.exists():
        r = _git("clone", "--quiet", "--bare", "--filter=blob:none", url, str(target))
        if r.returncode != 0:
            raise RuntimeError("cannot clone %s: %s" % (url, r.stderr.strip()))
    return _git("cat-file", "-e", sha + "^{commit}", cwd=str(target)).returncode == 0


def tag_exists(url: str, tag: str) -> bool:
    r = _git("ls-remote", "--tags", url, "refs/tags/%s" % tag)
    if r.returncode != 0:
        raise RuntimeError("cannot read %s: %s" % (url, r.stderr.strip()))
    return bool(r.stdout.strip())


def check(root: Path, log=print) -> list[str]:
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        for b in od.collect(root):
            f = b.fields
            where = "%s:%d" % (Path(b.file).relative_to(root), b.start + 1)
            try:
                if b.type == "git_branch":
                    ok = commit_exists(f["path"], f["version"], Path(tmp))
                    what = "commit %s" % f["version"][:10]
                elif b.type == "git":
                    ok = tag_exists(f["path"], f["version"])
                    what = "tag %s" % f["version"]
                else:
                    continue
            except RuntimeError as exc:
                problems.append("%s: %s" % (where, exc))
                continue
            if not ok:
                problems.append("%s: %s not found in %s" % (where, what, f["path"]))
            else:
                log("ok   %-40s %s" % (od.repo_name_from_path(f["path"]), what))
    for p in problems:
        log("FAIL " + p)
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(HERE.parent))
    a = ap.parse_args(argv)
    return 1 if check(Path(a.root)) else 0


if __name__ == "__main__":
    sys.exit(main())
