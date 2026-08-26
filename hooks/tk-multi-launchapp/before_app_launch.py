# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Before App Launch Hook
This hook is executed prior to application launch and is useful if you need
to set environment variables or run scripts as part of the app initialization.
"""

import os
from sgtk.util import shotgun
import sgtk


class BeforeAppLaunch(sgtk.Hook):
    """
    Hook to set up the system prior to app launch.
    """

    def execute(self, app_path, app_args, version, engine_name, **kwargs):
        # Get ShotGrid connection
        sg = shotgun.get_sg_connection()

        # Finding current project name
        current_engine = sgtk.platform.current_engine()
        current_context = current_engine.context
        project_name = current_context.project["name"]

        # Get template
        primary_location = self.parent.sgtk.roots.get('primary')

        # Get core
        tk = sgtk.sgtk_from_path(primary_location)

        # Get OCIO path
        ocio_template = tk.templates["ocio_config"]
        ocio_path = ocio_template.apply_fields(current_context).replace(os.sep, '/')

        if os.path.isfile(ocio_path):
            os.environ["OCIO"] = ocio_path
            self.parent.log_info("OCIO config found, set environment")

        if engine_name == "tk-houdini":
            ########################################
            """Setting splash screen"""
            splash = self.parent.engine.apps.get('tk-houdini-splashscreen')
            if splash is not None:
                self.parent.log_info('Initializing Houdini Splash Screen')
                splash.create_splash(app_path, app_args, version)
            else:
                self.parent.log_info('Something went wrong while initializing tk-houdini-splashscreen')

            ########################################
            """Setting render engine environment"""

            # Finding render engine entity
            render_engine = sg.find_one("Project", [["name", "is", project_name]], ["sg_render_engine"]).get(
                'sg_render_engine')

            # Setting render engine environment
            if not render_engine is None:
                self.parent.log_info("Set render_engine environment to %s" % render_engine)
                os.environ["RENDER_ENGINE"] = render_engine

            else:
                self.parent.log_info("No render engine entity set in ShotGrid project")

            ########################################
            """Setting OTL scan path"""

            # Get template
            houdini_otls_template = tk.templates["houdini_otls"]
            otls_path = houdini_otls_template.apply_fields(current_context).replace(os.sep, '/')

            # Check if HOUDINI_OTLSCAN_PATH exists in environment, if it's empty add the default value back
            HOUDINI_OTLSCAN_PATH = os.environ.get("HOUDINI_OTLSCAN_PATH")
            if HOUDINI_OTLSCAN_PATH is None or HOUDINI_OTLSCAN_PATH == "":
                sgtk.util.append_path_to_env_var("HOUDINI_OTLSCAN_PATH", "@/otls")

            # Add the project otls path to the environment
            sgtk.util.append_path_to_env_var("HOUDINI_OTLSCAN_PATH", otls_path)

            self.parent.log_info("Added otlscan path %s" % otls_path)

        if engine_name == "tk-nuke":
            ########################################
            """Staging project settings for Nuke to read on startup"""

            # The tk-nuke-projectsettings Toolkit app (registered on
            # settings.tk-nuke.shot_step) does a live ShotGrid query and
            # applies fps/frame range to nuke.root() via addOnCreate/
            # addOnScriptLoad callbacks - that's the primary mechanism.
            # This hook only stages the same values as env vars, used by
            # that app as a fallback if its live query fails. It runs
            # before the Nuke process exists, so it cannot touch
            # nuke.root() itself.

            project_fields = sg.find_one(
                "Project",
                [["name", "is", project_name]],
                ["sg_fps", "sg_render_engine"],
            )

            fps = project_fields.get("sg_fps") if project_fields else None
            if fps is not None:
                self.parent.log_info("Set NFA_PROJECT_FPS environment to %s" % fps)
                os.environ["NFA_PROJECT_FPS"] = str(fps)
            else:
                self.parent.log_info("No sg_fps set on ShotGrid project")

            render_engine = (
                project_fields.get("sg_render_engine") if project_fields else None
            )
            if render_engine is not None:
                self.parent.log_info(
                    "Set RENDER_ENGINE environment to %s" % render_engine
                )
                os.environ["RENDER_ENGINE"] = render_engine
            else:
                self.parent.log_info("No render engine entity set in ShotGrid project")

            # Shot frame range, only meaningful when context is a Shot
            if current_context.entity and current_context.entity["type"] == "Shot":
                shot_fields = sg.find_one(
                    "Shot",
                    [["id", "is", current_context.entity["id"]]],
                    ["sg_cut_in", "sg_cut_out"],
                )
                cut_in = shot_fields.get("sg_cut_in") if shot_fields else None
                cut_out = shot_fields.get("sg_cut_out") if shot_fields else None
                if cut_in is not None and cut_out is not None:
                    os.environ["NFA_SHOT_CUT_IN"] = str(cut_in)
                    os.environ["NFA_SHOT_CUT_OUT"] = str(cut_out)
                    self.parent.log_info(
                        "Set NFA_SHOT_CUT_IN/OUT environment to %s/%s"
                        % (cut_in, cut_out)
                    )
                else:
                    self.parent.log_info(
                        "Shot is missing sg_cut_in/sg_cut_out, skipping frame range env"
                    )
