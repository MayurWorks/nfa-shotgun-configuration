# MIT License
#
# Copyright (c) 2026 SlateX
#
# publish2 plugin that runs after the Nuke script has been published. It
#   - moves the Task to a configurable status (e.g. "rev" = Pending Review)
#   - posts a Note on the Shot linking the new version, with the artist's
#     publish comment
#
# It never fails the publish: every ShotGrid error is logged as a warning, the
# artist's files are already published by then.

import importlib.util
import os

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


def load_sibling(hook_dir, name):
    path = os.path.join(hook_dir, name + ".py")
    spec = importlib.util.spec_from_file_location("sx_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def valid_status_codes(sg):
    """Status codes this site defines for Task.sg_status_list, or None if the
    schema cannot be read."""
    try:
        field = sg.schema_field_read("Task", "sg_status_list")["sg_status_list"]
        return set(field["properties"]["valid_values"]["value"])
    except Exception:
        return None


class UpdateTaskStatusPlugin(HookBaseClass):

    @property
    def name(self):
        return "Update Task Status and Notify"

    @property
    def description(self):
        return """
        After a successful publish, sets the Task status and posts a Note on the
        Shot with the publish comment and a link to the published file.
        Leave <b>Status After Publish</b> empty to only post the note.
        """

    @property
    def icon(self):
        return os.path.join(self.disk_location, os.pardir, "icons", "publish.png")

    @property
    def settings(self):
        return {
            "Status After Publish": {
                "type": "str", "default": "",
                "description": "Task status code to set after publishing, e.g. rev. Empty = leave unchanged.",
            },
            "Post Note": {
                "type": "bool", "default": True,
                "description": "Post a Note on the Shot linking the published file.",
            },
        }

    @property
    def item_filters(self):
        return ["nuke.session"]

    def accept(self, settings, item):
        return {"accepted": True, "checked": True}

    def validate(self, settings, item):
        return True

    def publish(self, settings, item):
        pass

    # ------------------------------------------------------------------ finalize
    def finalize(self, settings, item):
        health = load_sibling(self.disk_location, "pipeline_health")
        sg = self.parent.shotgun
        ctx = self.parent.context
        publish = item.properties.get("sg_publish_data")

        status = (settings["Status After Publish"].value or "").strip()
        if status:
            self._set_status(sg, ctx, status)

        if settings["Post Note"].value:
            self._post_note(sg, ctx, item, publish)

        health.log_event(
            "publish_finalize",
            context=str(ctx),
            published_file=(publish or {}).get("id"),
            status=status or None,
        )

    def _set_status(self, sg, ctx, status):
        task = ctx.task
        if not task:
            self.logger.warning("No task in context, status not changed.")
            return
        codes = valid_status_codes(sg)
        if codes is not None and status not in codes:
            self.logger.warning(
                "Status '%s' is not defined on this site (valid: %s); left unchanged."
                % (status, ", ".join(sorted(codes)))
            )
            return
        try:
            sg.update("Task", task["id"], {"sg_status_list": status})
            self.logger.info("Task status set to '%s'." % status)
        except Exception as exc:
            self.logger.warning("Could not set task status: %s" % exc)

    def _post_note(self, sg, ctx, item, publish):
        entity = ctx.entity
        if not entity:
            return
        comment = (item.description or "").strip() or "(no comment)"
        links = [entity]
        if publish:
            links.append({"type": publish["type"], "id": publish["id"]})
        data = {
            "project": ctx.project,
            "note_links": links,
            "subject": "Published %s" % (item.properties.get("publish_name") or ctx.entity.get("name", "")),
            "content": comment,
        }
        if ctx.user:
            data["user"] = ctx.user
        if ctx.task:
            data["tasks"] = [ctx.task]
        try:
            sg.create("Note", data)
            self.logger.info("Note posted on %s." % entity.get("name", entity.get("type")))
        except Exception as exc:
            self.logger.warning("Could not post note: %s" % exc)
