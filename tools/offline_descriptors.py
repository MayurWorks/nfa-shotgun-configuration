#!/usr/bin/env python3
"""
Make a Toolkit configuration installable without Internet access.

Artist machines cannot reach the App Store or GitHub, so every app, engine,
framework (and core) descriptor has to point at a git mirror inside the studio
network. This tool

  status   lists descriptors that still need the Internet
  rewrite  points them at the internal mirror (comments and layout are kept)
  sync     copies the upstream repos they reference into the internal mirror
  check    verifies every mirrored tag / branch exists on the mirror

Descriptor mapping
  app_store      name: N, version: vX   ->  type: git, path: <base>/N.git, version: vX
  github_release repository: R, version: V -> type: git, path: <base>/R.git, version: V
  git_branch     path: <url>/X.git      ->  same branch and pinned SHA, path: <base>/X.git
  git            path: <url>/X.git      ->  path: <base>/X.git

<base> is --mirror-base, e.g. git@git.studio.local:pipeline or file:///srv/git.
Tags are assumed to match the version string (App Store versions are vX.Y.Z git
tags in the shotgunsoftware repos; NFA releases are tagged with the bare
version). `check` tells you when that assumption is wrong for a given repo.

Examples
  offline_descriptors.py status
  offline_descriptors.py rewrite --mirror-base git@git.studio.local:pipeline --dry-run
  offline_descriptors.py sync    --mirror-base file:///srv/git --cache /var/cache/mirror
  offline_descriptors.py check   --mirror-base git@git.studio.local:pipeline
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

FIELDS = ("type", "name", "version", "organization", "repository", "path", "branch")
REMOTE_TYPES = ("app_store", "github_release", "git_branch", "git")
FIELD_RE = re.compile(r"^(?P<indent>[ ]*)(?P<key>%s):[ ]*(?P<value>.*?)[ ]*$" % "|".join(FIELDS))
GITHUB = "https://github.com"
SHOTGUN_ORG = "shotgunsoftware"


class Block:
    def __init__(self, file, start, end, indent, fields):
        self.file, self.start, self.end = file, start, end  # end exclusive
        self.indent, self.fields = indent, fields

    @property
    def type(self):
        return self.fields.get("type")


def config_files(root: Path):
    files = sorted((root / "env").rglob("*.yml")) + sorted((root / "core").glob("*.yml"))
    return [f for f in files if f.is_file()]


def find_blocks(file: Path, lines: list[str]) -> list[Block]:
    blocks, i = [], 0
    while i < len(lines):
        m = FIELD_RE.match(lines[i])
        if not (m and m["key"] == "type" and m["value"] in REMOTE_TYPES):
            i += 1
            continue
        indent = m["indent"]
        start = i
        while start > 0 and _same_indent_field(lines[start - 1], indent):
            start -= 1
        end = i + 1
        while end < len(lines) and _same_indent_field(lines[end], indent):
            end += 1
        fields = {}
        for line in lines[start:end]:
            fm = FIELD_RE.match(line)
            fields[fm["key"]] = fm["value"].strip("'\"")
        blocks.append(Block(file, start, end, indent, fields))
        i = end
    return blocks


def _same_indent_field(line, indent):
    m = FIELD_RE.match(line)
    return bool(m) and m["indent"] == indent


def join(base: str, repo: str) -> str:
    return "%s/%s.git" % (base.rstrip("/"), repo)


def repo_name_from_path(path: str) -> str:
    name = path.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def to_mirror(fields: dict, base: str) -> dict:
    t = fields["type"]
    if t == "app_store":
        return {"type": "git", "path": join(base, fields["name"]), "version": fields["version"]}
    if t == "github_release":
        return {"type": "git", "path": join(base, fields["repository"]), "version": fields["version"]}
    if t in ("git", "git_branch"):
        out = dict(fields)
        out["path"] = join(base, repo_name_from_path(fields["path"]))
        return out
    raise ValueError("unsupported descriptor type %s" % t)


def upstream_of(fields: dict, upstream_base: str = GITHUB):
    """(clone url, ref) of the public repo behind a descriptor."""
    t = fields["type"]
    if t == "app_store":
        return "%s/%s/%s.git" % (upstream_base, SHOTGUN_ORG, fields["name"]), fields["version"]
    if t == "github_release":
        return "%s/%s/%s.git" % (upstream_base, fields["organization"], fields["repository"]), fields["version"]
    return fields["path"], fields.get("version") or fields.get("branch")


def render(block: Block, fields: dict) -> list[str]:
    order = [k for k in FIELDS if k in fields]
    return ["%s%s: %s" % (block.indent, k, fields[k]) for k in order]


def is_internal(fields: dict, base: str) -> bool:
    return fields.get("type") in ("git", "git_branch") and fields.get("path", "").startswith(base.rstrip("/") + "/")


def collect(root: Path):
    out = []
    for f in config_files(root):
        lines = f.read_text().split("\n")
        out += find_blocks(f, lines)
    return out


# -------------------------------------------------------------------- commands
def cmd_status(root, base=None):
    pending = [b for b in collect(root) if not (base and is_internal(b.fields, base))]
    for b in pending:
        print("%-40s %-15s %s" % (os.path.relpath(b.file, root), b.type,
                                  b.fields.get("name") or b.fields.get("repository") or b.fields.get("path")))
    print("\n%d descriptor(s) still depend on the Internet" % len(pending))
    return pending


def cmd_rewrite(root, base, dry_run=False):
    changed = 0
    for f in config_files(root):
        lines = f.read_text().split("\n")
        blocks = find_blocks(f, lines)
        for b in reversed(blocks):  # bottom-up so indexes stay valid
            if is_internal(b.fields, base):
                continue
            new = render(b, to_mirror(b.fields, base))
            lines[b.start:b.end] = new
            changed += 1
        if blocks and not dry_run:
            f.write_text("\n".join(lines))
    print("%s %d descriptor(s)" % ("would rewrite" if dry_run else "rewrote", changed))
    return changed


def git(*args, cwd=None, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def cmd_sync(root, base, cache, upstream_base=GITHUB, dry_run=False):
    """Copy every upstream repo referenced by the ORIGINAL descriptors (run this
    before `rewrite`, or from a clean checkout of the public config) into the mirror."""
    cache = Path(cache)
    seen = {}
    for b in collect(root):
        if is_internal(b.fields, base):
            continue
        url, ref = upstream_of(b.fields, upstream_base)
        seen.setdefault(url, set()).add(ref)
    for url, refs in sorted(seen.items()):
        name = repo_name_from_path(url)
        target = join(base, name)
        print("%s -> %s  (%s)" % (url, target, ", ".join(sorted(r for r in refs if r))))
        if dry_run:
            continue
        local = cache / (name + ".git")
        if local.is_dir():
            git("remote", "update", "--prune", cwd=local)
        else:
            cache.mkdir(parents=True, exist_ok=True)
            git("clone", "--mirror", url, str(local))
        if target.startswith("file://") or target.startswith("/"):
            dest = Path(target.replace("file://", ""))
            if not dest.exists():
                dest.mkdir(parents=True)
                git("init", "--bare", str(dest))
        git("push", "--mirror", target, cwd=local)
    return seen


def cmd_check(root, base):
    problems = []
    for b in collect(root):
        if not is_internal(b.fields, base):
            problems.append("not mirrored: %s" % (b.fields.get("name") or b.fields.get("repository") or b.fields.get("path")))
            continue
        path, ref = b.fields["path"], b.fields.get("version") or b.fields.get("branch")
        if b.type == "git_branch":
            ref = b.fields["branch"]
        out = git("ls-remote", path, ref, "refs/tags/%s" % ref, "refs/heads/%s" % ref, check=False)
        if out.returncode != 0:
            problems.append("cannot read %s: %s" % (path, out.stderr.strip().splitlines()[-1:] or ""))
        elif not out.stdout.strip():
            problems.append("%s has no tag/branch '%s'" % (path, ref))
    for p in problems:
        print("PROBLEM", p)
    print("%d problem(s)" % len(problems))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("status", "rewrite", "sync", "check"))
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="config repo root")
    ap.add_argument("--mirror-base")
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/offline-mirror"))
    ap.add_argument("--upstream-base", default=GITHUB)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root)

    if a.command == "status":
        return 1 if cmd_status(root, a.mirror_base) else 0
    if not a.mirror_base:
        ap.error("--mirror-base is required")
    if a.command == "rewrite":
        cmd_rewrite(root, a.mirror_base, a.dry_run)
        return 0
    if a.command == "sync":
        cmd_sync(root, a.mirror_base, a.cache, a.upstream_base, a.dry_run)
        return 0
    return 1 if cmd_check(root, a.mirror_base) else 0


if __name__ == "__main__":
    sys.exit(main())
