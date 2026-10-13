# MIT License
#
# Copyright (c) 2026 SlateX
#
# Loader actions for Nuke: after the stock "Create Read Node", set the Read
# node's colorspace from the shot's colour pipeline so artists never have to.
#
#   Plate (ingested EXR)        -> plate_read_colorspace of the pipeline
#   Rendered Image (EXR)        -> working colorspace of the pipeline
#
# Anything else, or anything that cannot be resolved, is left exactly as the
# stock hook created it.

import os

import nuke
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

PLATE_TYPES = ("Plate", "Hiero Plate")
RENDER_TYPES = ("Rendered Image",)


class NukeActions(HookBaseClass):

    def _create_read_node(self, path, sg_publish_data):
        super(NukeActions, self)._create_read_node(path, sg_publish_data)
        try:
            self._set_read_colorspace(path, sg_publish_data)
        except Exception as exc:
            self.logger.warning("Could not set Read colorspace: %s" % exc)

    # ------------------------------------------------------------------
    def _wanted_colorspace(self, path, sg_publish_data, expected):
        if not path.lower().endswith(".exr"):
            return None
        type_name = (sg_publish_data.get("published_file_type") or {}).get("name")
        if type_name in PLATE_TYPES:
            return expected.get("plate_read_colorspace")
        if type_name in RENDER_TYPES:
            return expected.get("working_colorspace")
        return None

    def _set_read_colorspace(self, path, sg_publish_data):
        app = self.parent.engine.apps.get("tk-nuke-projectsettings")
        if app is None:
            return
        expected = app.get_expected_script_settings(self.parent.context)
        wanted = self._wanted_colorspace(path, sg_publish_data, expected or {})
        if not wanted:
            return

        node = nuke.selectedNode()  # createNode leaves the new node selected
        if node.Class() != "Read":
            return
        knob = node["colorspace"]
        if knob.value() == wanted:
            return
        knob.setValue(wanted)
        if knob.value() != wanted:
            self.logger.warning(
                "Colorspace '%s' is not available in this OCIO config; Read left at '%s'."
                % (wanted, knob.value())
            )
