import sys
import types

import pytest

from conftest import HOOKS, load_module


# --------------------------------------------------------------------- fake nuke
class Knob:
    def __init__(self, v): self.v = v
    def value(self): return self.v


class Fmt:
    def __init__(self, w, h): self._w, self._h = w, h
    def width(self): return self._w
    def height(self): return self._h


class Node:
    def __init__(self, cls, name, file=None, disable=False, first=1001, last=1003, managed=False):
        self.c, self.n = cls, name
        self.k = {"file": Knob(file), "disable": Knob(disable), "first": Knob(first), "last": Knob(last)}
        if managed:
            self.k["tk_profile_list"] = Knob("x")

    def Class(self): return self.c
    def fullName(self): return self.n
    def knobs(self): return self.k
    def __getitem__(self, key): return self.k[key]


class Root:
    def __init__(self, **kw):
        self.vals = dict(fps=24.0, first_frame=1001, last_frame=1085, w=1920, h=1080,
                         ocio="aces_1.2", ws="ACES - ACEScg")
        self.vals.update(kw)

    def fps(self): return self.vals["fps"]
    def format(self): return Fmt(self.vals["w"], self.vals["h"])

    def __getitem__(self, key):
        return Knob({"first_frame": self.vals["first_frame"], "last_frame": self.vals["last_frame"],
                     "OCIO_config": self.vals["ocio"], "workingSpaceLUT": self.vals["ws"]}[key])


@pytest.fixture
def nuke_env(monkeypatch):
    state = {"root": Root(), "nodes": []}
    nuke = types.ModuleType("nuke")
    nuke.root = lambda: state["root"]
    nuke.allNodes = lambda recurseGroups=False: list(state["nodes"])
    monkeypatch.setitem(sys.modules, "nuke", nuke)
    return state


class Setting:
    def __init__(self, v): self.value = v


class App:
    def __init__(self, expected): self.expected = expected
    def get_expected_script_settings(self, ctx): return self.expected


class Parent:
    def __init__(self, expected, roots=("/jobs",)):
        self.engine = types.SimpleNamespace(apps={"tk-nuke-projectsettings": App(expected)} if expected is not None else {})
        self.sgtk = types.SimpleNamespace(roots={"primary": "/jobs"})
        self.context = "ctx"
        self.shotgun = None


def make_plugin(parent):
    mod = load_module("validate_shot_settings", HOOKS / "validate_shot_settings.py")
    return mod.ValidateShotSettingsPlugin(parent)


S = {"Check Settings": Setting(True), "Check Nodes": Setting(True)}

GOOD = dict(fps=24.0, first_frame=1001, last_frame=1085, width=1920, height=1080,
            ocio_config="aces_1.2", working_colorspace="ACES - ACEScg")


def test_missing_read_files_block(nuke_env, tmp_path):
    f = tmp_path / "a.1001.exr"; f.write_text("x")
    nuke_env["nodes"] = [Node("Read", "Read1", file="/jobs/x/a.%04d.exr")]
    p = make_plugin(Parent(GOOD))
    # the file is under /jobs, which does not exist here, so Read exists=False -> error
    assert p.validate(S, None) is False
    assert any("do not exist" in m for m in p.logger.levels("error"))


def test_passes_when_files_exist(nuke_env, tmp_path, monkeypatch):
    for fr in (1001, 1003):
        (tmp_path / ("a.%d.exr" % fr)).write_text("x")
    nuke_env["nodes"] = [Node("Read", "Read1", file=str(tmp_path / "a.%04d.exr").replace("%04d", "%d"))]
    p = make_plugin(Parent(GOOD))
    p.parent.sgtk.roots = {"primary": str(tmp_path)}
    assert p.validate(S, None) is True
    assert p.logger.levels("error") == []


def test_wrong_fps_blocks(nuke_env):
    nuke_env["root"] = Root(fps=25.0)
    p = make_plugin(Parent(GOOD))
    assert p.validate({"Check Settings": Setting(True), "Check Nodes": Setting(False)}, None) is False
    assert "fps" in p.logger.levels("error")[0]


def test_settings_check_skipped_without_app(nuke_env):
    p = make_plugin(Parent(None))
    assert p.validate({"Check Settings": Setting(True), "Check Nodes": Setting(False)}, None) is True


def test_unresolvable_settings_warn_not_block(nuke_env):
    p = make_plugin(Parent({}))
    assert p.validate({"Check Settings": Setting(True), "Check Nodes": Setting(False)}, None) is True
    assert p.logger.levels("warning")


def test_local_write_path_blocks(nuke_env):
    nuke_env["nodes"] = [Node("Write", "Write1", file="/home/artist/out.%04d.exr")]
    p = make_plugin(Parent(GOOD))
    assert p.validate({"Check Settings": Setting(False), "Check Nodes": Setting(True)}, None) is False


def test_details_attached_for_error(nuke_env):
    nuke_env["nodes"] = [Node("Write", "WriteX", file="/tmp/o.exr")]
    p = make_plugin(Parent(GOOD))
    p.validate({"Check Settings": Setting(False), "Check Nodes": Setting(True)}, None)
    extra = [e for l, m, e in p.logger.records if l == "error"][0]
    assert "WriteX" in extra["action_show_more_info"]["text"]


# ------------------------------------------------------------- status/note plugin
class SG:
    def __init__(self, codes=("rdy", "ip", "rev"), fail_update=False):
        self.codes, self.fail_update = codes, fail_update
        self.updated, self.created = [], []

    def schema_field_read(self, et, field):
        return {field: {"properties": {"valid_values": {"value": list(self.codes)}}}}

    def update(self, et, i, data):
        if self.fail_update:
            raise RuntimeError("nope")
        self.updated.append((et, i, data))

    def create(self, et, data):
        self.created.append((et, data))
        return {"type": et, "id": 1}


class Item:
    description = "Fixed edge matte"
    properties = {"sg_publish_data": {"type": "PublishedFile", "id": 55}, "publish_name": "S1_comp_v003"}


def status_plugin(sg, task=True, user=True):
    mod = load_module("update_task_status", HOOKS / "update_task_status.py")
    ctx = types.SimpleNamespace(
        task={"type": "Task", "id": 9} if task else None,
        entity={"type": "Shot", "id": 5, "name": "S1"},
        project={"type": "Project", "id": 1},
        user={"type": "HumanUser", "id": 2} if user else None,
    )
    parent = types.SimpleNamespace(shotgun=sg, context=ctx)
    return mod.UpdateTaskStatusPlugin(parent)


def test_sets_status_and_posts_note():
    sg = SG()
    p = status_plugin(sg)
    p.finalize({"Status After Publish": Setting("rev"), "Post Note": Setting(True)}, Item())
    assert sg.updated == [("Task", 9, {"sg_status_list": "rev"})]
    et, data = sg.created[0]
    assert et == "Note" and data["content"] == "Fixed edge matte"
    assert {"type": "PublishedFile", "id": 55} in data["note_links"]
    assert data["tasks"] == [{"type": "Task", "id": 9}]


def test_unknown_status_is_not_applied():
    sg = SG(codes=("rdy", "ip"))
    p = status_plugin(sg)
    p.finalize({"Status After Publish": Setting("rev"), "Post Note": Setting(False)}, Item())
    assert sg.updated == [] and any("not defined" in m for m in p.logger.levels("warning"))


def test_empty_status_only_posts_note():
    sg = SG()
    p = status_plugin(sg)
    p.finalize({"Status After Publish": Setting(""), "Post Note": Setting(True)}, Item())
    assert sg.updated == [] and len(sg.created) == 1


def test_shotgun_failure_never_raises():
    sg = SG(fail_update=True)
    p = status_plugin(sg)
    p.finalize({"Status After Publish": Setting("rev"), "Post Note": Setting(False)}, Item())
    assert any("Could not set" in m for m in p.logger.levels("warning"))


def test_no_task_in_context():
    sg = SG()
    p = status_plugin(sg, task=False)
    p.finalize({"Status After Publish": Setting("rev"), "Post Note": Setting(True)}, Item())
    assert sg.updated == [] and "tasks" not in sg.created[0][1]
