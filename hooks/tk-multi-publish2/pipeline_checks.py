# MIT License
#
# Copyright (c) 2026 SlateX
#
# Pure-python checks used by the publish2 validation plugin. No Nuke / sgtk
# imports so they can be unit tested outside a DCC; the plugin gathers the
# facts from Nuke and passes plain values in.

import os
import re

# Paths that only exist on one artist's machine and break on the farm / for
# other artists. Case-insensitive prefix match on the normalised path.
LOCAL_PATH_PREFIXES = (
    "/home/", "/tmp/", "/var/tmp/", "/users/", "/root/",
    "c:/users/", "c:/temp/", "d:/", "e:/",
)

FPS_TOLERANCE = 0.001


class Finding(object):
    ERROR = "error"
    WARNING = "warning"

    def __init__(self, level, message, details=None):
        self.level = level
        self.message = message
        self.details = details or []

    def __repr__(self):
        return "Finding(%s, %r)" % (self.level, self.message)


def normalise(path):
    return (path or "").replace("\\", "/")


def is_local_path(path, project_roots=()):
    """True when ``path`` lives on the artist's own disk rather than on the
    shared project storage. Anything under a project root is never local."""
    p = normalise(path)
    if not p or "[" in p:  # empty or a TCL expression we cannot judge
        return False
    low = p.lower()
    for root in project_roots:
        r = normalise(root).rstrip("/").lower()
        if r and (low == r or low.startswith(r + "/")):
            return False
    return low.startswith(LOCAL_PATH_PREFIXES)


def check_settings(actual, expected):
    """
    Compare the script's settings with what the pipeline resolved for the shot.

    ``actual`` / ``expected`` are dicts with optional keys: fps, first_frame,
    last_frame, width, height, ocio_config, working_colorspace. Keys missing
    from ``expected`` are not checked (the pipeline has no opinion).
    """
    findings = []

    exp = expected.get("fps")
    if exp is not None and abs(float(actual.get("fps", 0)) - float(exp)) > FPS_TOLERANCE:
        findings.append(Finding(
            Finding.ERROR,
            "Script fps is %s but the shot expects %s." % (actual.get("fps"), exp)))

    for key, label in (("first_frame", "first frame"), ("last_frame", "last frame")):
        exp = expected.get(key)
        if exp is not None and int(actual.get(key, -1)) != int(exp):
            findings.append(Finding(
                Finding.ERROR,
                "Script %s is %s but the shot cut has %s." % (label, actual.get(key), exp)))

    ew, eh = expected.get("width"), expected.get("height")
    if ew and eh and (int(actual.get("width", 0)), int(actual.get("height", 0))) != (int(ew), int(eh)):
        findings.append(Finding(
            Finding.ERROR,
            "Script format is %sx%s but the shot expects %sx%s."
            % (actual.get("width"), actual.get("height"), ew, eh)))

    exp = expected.get("ocio_config")
    if exp:
        got = actual.get("ocio_config") or ""
        if _norm_name(exp) not in _norm_name(got):
            findings.append(Finding(
                Finding.ERROR,
                "OCIO config is '%s' but the shot expects '%s'." % (got, exp)))

    exp = expected.get("working_colorspace")
    if exp and actual.get("working_colorspace") not in (None, exp):
        findings.append(Finding(
            Finding.WARNING,
            "Working colorspace is '%s' but the shot expects '%s'."
            % (actual.get("working_colorspace"), exp)))

    return findings


def _norm_name(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def check_nodes(nodes, project_roots=()):
    """
    ``nodes`` is a list of dicts: {name, class, file, disabled, exists}.
    ``exists`` is True/False for Read nodes (frame range present on disk) and
    None when not applicable.
    """
    findings = []

    missing = [n["name"] for n in nodes
               if n["class"] == "Read" and not n.get("disabled") and n.get("exists") is False]
    if missing:
        findings.append(Finding(
            Finding.ERROR,
            "%d Read node(s) point at files that do not exist." % len(missing),
            missing))

    empty = [n["name"] for n in nodes
             if n["class"] == "Read" and not n.get("disabled") and not n.get("file")]
    if empty:
        findings.append(Finding(
            Finding.ERROR, "%d Read node(s) have no file path." % len(empty), empty))

    local = [("%s: %s" % (n["name"], n["file"])) for n in nodes
             if n["class"] in ("Read", "Write") and not n.get("disabled")
             and is_local_path(n.get("file"), project_roots)]
    if local:
        findings.append(Finding(
            Finding.ERROR,
            "%d node(s) use a path on a local disk; other artists and the farm cannot see it." % len(local),
            local))

    disabled_writes = [n["name"] for n in nodes
                       if n["class"] == "Write" and n.get("disabled") and n.get("sg_managed")]
    if disabled_writes:
        findings.append(Finding(
            Finding.WARNING,
            "%d pipeline Write node(s) are disabled and will not render." % len(disabled_writes),
            disabled_writes))

    return findings


def summarise(findings):
    errors = [f for f in findings if f.level == Finding.ERROR]
    warnings = [f for f in findings if f.level == Finding.WARNING]
    return errors, warnings
