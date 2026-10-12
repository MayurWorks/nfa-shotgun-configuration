# MIT License
#
# Copyright (c) 2026 SlateX
#
# publish2 validation plugin for a Nuke session. Blocks a publish when the
# script no longer matches what the pipeline set up for the shot, or contains
# nodes that will break for other artists / the farm.
#
# Checks
#   - fps, cut range, explicit format, OCIO config vs the shot's resolved
#     pipeline settings (tk-nuke-projectsettings.get_expected_script_settings)
#   - Read nodes with no path or with files missing on disk
#   - Read / Write nodes using a path on a local disk
#   - pipeline Write nodes left disabled (warning)
#
# Errors block the publish; warnings do not.

import importlib.util
import os

import nuke
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


def load_sibling(hook_dir, name):
    """Hooks are loaded by file path, not imported, so the plain-python helper
    modules next to this file are loaded by path too."""
    path = os.path.join(hook_dir, name + ".py")
    spec = importlib.util.spec_from_file_location("sx_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ValidateShotSettingsPlugin(HookBaseClass):

    @property
    def name(self):
        return "Validate Shot Settings"

    @property
    def description(self):
        return """
        Checks the script before publishing:
        <ul>
        <li>fps, frame range, format and OCIO config match the shot</li>
        <li>every Read node has a path and its files exist</li>
        <li>no Read/Write node points at a local disk</li>
        </ul>
        Problems that would break the shot for other artists or the farm block
        the publish; softer issues are shown as warnings.
        """

    @property
    def icon(self):
        return os.path.join(self.disk_location, os.pardir, "icons", "review.png")

    @property
    def settings(self):
        return {
            "Check Settings": {
                "type": "bool", "default": True,
                "description": "Compare fps/range/format/OCIO with the shot.",
            },
            "Check Nodes": {
                "type": "bool", "default": True,
                "description": "Check Read/Write nodes for missing or local paths.",
            },
        }

    @property
    def item_filters(self):
        return ["nuke.session"]

    def accept(self, settings, item):
        return {"accepted": True, "checked": True}

    # ------------------------------------------------------------------ facts
    def _actual_settings(self):
        root = nuke.root()
        fmt = root.format()
        return {
            "fps": root.fps(),
            "first_frame": int(root["first_frame"].value()),
            "last_frame": int(root["last_frame"].value()),
            "width": fmt.width(),
            "height": fmt.height(),
            "ocio_config": self._knob(root, "OCIO_config"),
            "working_colorspace": self._knob(root, "workingSpaceLUT"),
        }

    @staticmethod
    def _knob(node, name):
        try:
            return node[name].value()
        except Exception:
            return None

    def _node_facts(self):
        facts = []
        for node in nuke.allNodes(recurseGroups=True):
            cls = node.Class()
            if cls not in ("Read", "Write"):
                continue
            path = self._knob(node, "file")
            exists = None
            if cls == "Read" and path:
                exists = self._read_exists(node, path)
            facts.append({
                "name": node.fullName(),
                "class": cls,
                "file": path,
                "disabled": bool(self._knob(node, "disable")),
                "exists": exists,
                "sg_managed": "tk_profile_list" in node.knobs(),
            })
        return facts

    @staticmethod
    def _read_exists(node, path):
        if "%" not in path and "#" not in path:
            return os.path.exists(path)
        try:
            first = int(node["first"].value())
            last = int(node["last"].value())
            # first and last frame is enough to catch a missing sequence
            # without stat-ing every frame of a long shot
            for frame in (first, last):
                if "%" in path:
                    probe = path % frame
                else:
                    probe = path.replace("#" * path.count("#"), str(frame).zfill(path.count("#")))
                if not os.path.exists(probe):
                    return False
            return True
        except Exception:
            return None

    def _project_roots(self):
        try:
            return list(self.parent.sgtk.roots.values())
        except Exception:
            return []

    # ----------------------------------------------------------------- publish2
    def validate(self, settings, item):
        checks = load_sibling(self.disk_location, "pipeline_checks")
        health = load_sibling(self.disk_location, "pipeline_health")

        findings = []

        if settings["Check Settings"].value:
            findings += self._settings_findings(checks)

        if settings["Check Nodes"].value:
            findings += checks.check_nodes(self._node_facts(), self._project_roots())

        errors, warnings = checks.summarise(findings)

        for f in warnings:
            self.logger.warning(f.message, extra=self._more_info(f))
        for f in errors:
            self.logger.error(f.message, extra=self._more_info(f))

        health.log_event(
            "publish_validate",
            context=str(self.parent.context),
            errors=len(errors), warnings=len(warnings),
        )
        return not errors

    def _settings_findings(self, checks):
        app = self.parent.engine.apps.get("tk-nuke-projectsettings")
        if app is None:
            self.logger.debug("tk-nuke-projectsettings not loaded, settings check skipped")
            return []
        expected = app.get_expected_script_settings(self.parent.context)
        if not expected:
            self.logger.warning(
                "Could not resolve the shot's settings from ShotGrid; "
                "settings check skipped."
            )
            return []
        return checks.check_settings(self._actual_settings(), expected)

    @staticmethod
    def _more_info(finding):
        if not finding.details:
            return None
        return {
            "action_show_more_info": {
                "label": "Show Details",
                "tooltip": "Show the affected nodes",
                "text": "\n".join(finding.details),
            }
        }

    def publish(self, settings, item):
        pass

    def finalize(self, settings, item):
        pass
