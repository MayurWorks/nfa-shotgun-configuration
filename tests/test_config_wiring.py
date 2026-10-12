import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "env" / "includes" / "settings"
NUKE_SECTIONS = (
    "settings.tk-multi-publish2.nuke.asset_step",
    "settings.tk-multi-publish2.nuke.shot_step",
)


def _publish2():
    return yaml.safe_load((SETTINGS / "tk-multi-publish2.yml").read_text())


def test_every_config_hook_referenced_by_publish2_exists():
    text = (SETTINGS / "tk-multi-publish2.yml").read_text()
    for rel in set(re.findall(r"\{config\}/([\w\-./]+\.py)", text)):
        assert (ROOT / "hooks" / rel).is_file(), rel


def test_nuke_steps_validate_before_publish_and_notify_after():
    data = _publish2()
    for key in NUKE_SECTIONS:
        names = [p["name"] for p in data[key]["publish_plugins"]]
        assert names.index("Validate Shot Settings") < names.index("Publish to ShotGrid")
        assert names.index("Validate Render Completeness") < names.index("Publish to ShotGrid")
        # notify runs after the script publish so sg_publish_data exists
        last_publish = len(names) - 1 - names[::-1].index("Publish to ShotGrid")
        assert names.index("Update Task Status and Notify") > last_publish


def test_non_nuke_steps_unchanged():
    data = _publish2()
    for key, section in data.items():
        if "publish2.nuke." in key or not isinstance(section, dict):
            continue
        for plugin in section.get("publish_plugins", []):
            assert plugin["name"] != "Update Task Status and Notify", key
            assert plugin["name"] != "Validate Shot Settings", key


def test_status_is_opt_in():
    for key in NUKE_SECTIONS:
        plugin = next(p for p in _publish2()[key]["publish_plugins"]
                      if p["name"] == "Update Task Status and Notify")
        assert plugin["settings"]["Status After Publish"] == ""
