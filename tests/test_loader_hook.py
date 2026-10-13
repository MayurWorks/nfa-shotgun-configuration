import sys
import types

import pytest

import conftest
from conftest import HOOKS, ROOT, load_module

LOADER = ROOT / "hooks" / "tk-multi-loader2" / "tk-nuke_actions.py"


class Knob:
    def __init__(self, v, allowed=None):
        self.v, self.allowed = v, allowed

    def value(self):
        return self.v

    def setValue(self, v):
        if self.allowed is None or v in self.allowed:
            self.v = v


class ReadNode:
    def __init__(self, cs="default", allowed=None, cls="Read"):
        self._cls = cls
        self.k = {"colorspace": Knob(cs, allowed)}

    def Class(self): return self._cls
    def __getitem__(self, k): return self.k[k]


class Expected:
    def __init__(self, d): self.d = d
    def get_expected_script_settings(self, ctx): return self.d


@pytest.fixture
def hook(monkeypatch):
    node = ReadNode()
    nuke = types.ModuleType("nuke")
    nuke.selectedNode = lambda: node
    monkeypatch.setitem(sys.modules, "nuke", nuke)
    monkeypatch.setattr(conftest._Hook, "_create_read_node", lambda self, p, d: None, raising=False)
    mod = load_module("loader_actions", LOADER)
    h = mod.NukeActions(types.SimpleNamespace(
        context="ctx",
        engine=types.SimpleNamespace(apps={"tk-nuke-projectsettings": Expected(
            {"plate_read_colorspace": "ACES - ACEScg", "working_colorspace": "ACES - ACEScg"})}),
    ))
    h.node = node
    return h


def pub(type_name):
    return {"published_file_type": {"name": type_name}}


def test_plate_exr_gets_plate_colorspace(hook):
    hook._create_read_node("/p/a.%04d.exr", pub("Plate"))
    assert hook.node["colorspace"].value() == "ACES - ACEScg"


def test_rendered_exr_gets_working_colorspace(hook):
    hook._create_read_node("/p/a.%04d.exr", pub("Rendered Image"))
    assert hook.node["colorspace"].value() == "ACES - ACEScg"


def test_movie_left_alone(hook):
    hook._create_read_node("/p/ref.mov", pub("Plate"))
    assert hook.node["colorspace"].value() == "default"


def test_unknown_type_left_alone(hook):
    hook._create_read_node("/p/a.%04d.exr", pub("Texture"))
    assert hook.node["colorspace"].value() == "default"


def test_unavailable_colorspace_warns(hook):
    hook.node.k["colorspace"] = Knob("default", allowed=["default"])
    hook._create_read_node("/p/a.%04d.exr", pub("Plate"))
    assert hook.node["colorspace"].value() == "default"
    assert any("not available" in m for m in hook.logger.levels("warning"))


def test_non_read_node_untouched(hook):
    hook.node._cls = "ReadGeo2"
    hook._create_read_node("/p/a.%04d.exr", pub("Plate"))
    assert hook.node["colorspace"].value() == "default"


def test_no_projectsettings_app_is_fine(hook):
    hook.parent.engine.apps = {}
    hook._create_read_node("/p/a.%04d.exr", pub("Plate"))
    assert hook.node["colorspace"].value() == "default"


def test_errors_never_propagate(hook):
    hook.parent.engine.apps = {"tk-nuke-projectsettings": types.SimpleNamespace(
        get_expected_script_settings=lambda c: 1 / 0)}
    hook._create_read_node("/p/a.%04d.exr", pub("Plate"))
    assert hook.logger.levels("warning")
