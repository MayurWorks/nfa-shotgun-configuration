import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks" / "tk-multi-publish2"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Hook(object):
    """Stand-in for sgtk's Hook base class."""
    disk_location = str(HOOKS)

    def __init__(self, parent=None):
        self.parent = parent
        self.logger = _Logger()


class _Logger(object):
    def __init__(self):
        self.records = []

    def _add(self, level, msg, extra=None):
        self.records.append((level, msg, extra))

    def debug(self, msg, extra=None): self._add("debug", msg, extra)
    def info(self, msg, extra=None): self._add("info", msg, extra)
    def warning(self, msg, extra=None): self._add("warning", msg, extra)
    def error(self, msg, extra=None): self._add("error", msg, extra)

    def levels(self, level):
        return [m for l, m, _ in self.records if l == level]


def install_fake_sgtk():
    sgtk = types.ModuleType("sgtk")
    sgtk.get_hook_baseclass = lambda: _Hook
    sys.modules["sgtk"] = sgtk
    return sgtk


install_fake_sgtk()
