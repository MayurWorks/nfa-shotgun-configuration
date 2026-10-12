# MIT License
#
# Copyright (c) 2026 SlateX
#
# Append-only pipeline event log. One JSON object per line, one file per host
# per day, in a directory every workstation can write to. Never raises: logging
# must not be able to break an artist's publish.

import datetime
import getpass
import json
import os
import socket

ENV_DIR = "SX_PIPELINE_LOG_DIR"


def log_dir(default=None):
    return os.environ.get(ENV_DIR) or default


def log_event(event, directory=None, **fields):
    """Write one event. Returns the file path written, or None if disabled /
    failed. ``directory`` falls back to $SX_PIPELINE_LOG_DIR; with neither set
    the call is a no-op."""
    try:
        directory = directory or log_dir()
        if not directory:
            return None
        os.makedirs(directory, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc)
        host = socket.gethostname()
        path = os.path.join(directory, "%s_%s.jsonl" % (now.strftime("%Y-%m-%d"), host))
        record = {
            "ts": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "event": event,
            "host": host,
            "user": _user(),
        }
        record.update(fields)
        with open(path, "a") as fh:
            fh.write(json.dumps(record, default=str, sort_keys=True) + "\n")
        return path
    except Exception:
        return None


def _user():
    try:
        return getpass.getuser()
    except Exception:
        return ""


def summarise_day(directory, date=None):
    """Counts per event for one day across all hosts (used by the daily report)."""
    date = date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    counts = {}
    if not os.path.isdir(directory):
        return counts
    for name in sorted(os.listdir(directory)):
        if not (name.startswith(date) and name.endswith(".jsonl")):
            continue
        with open(os.path.join(directory, name)) as fh:
            for line in fh:
                try:
                    ev = json.loads(line).get("event", "?")
                except ValueError:
                    continue
                counts[ev] = counts.get(ev, 0) + 1
    return counts
