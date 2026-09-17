# MIT License
#
# Copyright (c) 2026 SlateX
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Studio override of tk-multi-workfiles2's stock scene_operation_tk-nuke.py.

Subclasses the app-bundled hook (via sgtk.get_hook_baseclass(), the
standard Toolkit pattern for extending a default hook rather than
duplicating it) so the existing "current_path"/"open"/"save"/"save_as"/
"reset" and Hiero/NukeStudio branch logic is inherited unchanged.

The only behaviour added: before a "save" or "save_as" operation
actually writes the script to disk, give tk-nuke-projectsettings a
chance to apply fps/frame range/OCIO/plate Read *first*, so those
values are correct in the file that gets written - not just correct in
a later session after the artist happens to open it again.

This deliberately only matters for a script that has never had settings
applied this session (see NukeProjectSettingsHandler.apply_settings_if_new
- e.g. a script built by hand, or any path that bypassed the normal
open/new-file triggers). A script that was already opened or
template-generated (and so already has settings applied, or has had
values deliberately changed by the artist since) is left alone on save.
"""

import sgtk

logger = sgtk.platform.get_logger(__name__)

HookClass = sgtk.get_hook_baseclass()


class SceneOperation(HookClass):
    def execute(
        self,
        operation,
        file_path,
        context,
        parent_action,
        file_version,
        read_only,
        **kwargs
    ):
        if operation in ("save", "save_as"):
            self._apply_projectsettings_before_save()

        return super(SceneOperation, self).execute(
            operation,
            file_path,
            context,
            parent_action,
            file_version,
            read_only,
            **kwargs
        )

    def _apply_projectsettings_before_save(self):
        """
        Looks up the tk-nuke-projectsettings app on the current engine
        and calls its apply_settings_if_new() entry point, if the app is
        present in this environment. Safe to call even when the app
        isn't configured (e.g. asset_step, where tk-nuke-projectsettings
        is Shot-scoped only) - just does nothing in that case.
        """
        try:
            engine = self.parent.engine
            projectsettings_app = engine.apps.get("tk-nuke-projectsettings")
            if projectsettings_app is None:
                return
            projectsettings_app.handler.apply_settings_if_new()
        except Exception:
            logger.warning(
                "scene_operation_tk-nuke: tk-nuke-projectsettings "
                "apply_settings_if_new() failed ahead of save",
                exc_info=True,
            )
