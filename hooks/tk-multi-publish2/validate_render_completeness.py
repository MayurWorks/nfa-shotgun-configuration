# Copyright (c) MayurWorks
#
# Publish2 validation plugin: blocks publishing of an incomplete render.
#
# Checks (image sequences produced by NukeSessionCollector.collect_sg_writenodes):
#   - every frame in the EXPECTED range exists on disk
#   - no frame is zero bytes
# Expected range = the write node's own range if "use limit to range" is on,
# otherwise the script range the collector stored on the item.
# Extra frames outside the range only produce a warning (e.g. stale frames left
# from an earlier render into the same version folder).
#
# Only "file.image.sequence" items are created by the collector for write nodes,
# so there is deliberately no movie filter here.

import os
import re

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


def _compress(numbers):
    numbers = sorted(numbers)
    out = []
    start = prev = numbers[0]
    for n in numbers[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append((start, prev))
        start = prev = n
    out.append((start, prev))
    return ", ".join(
        "%d" % a if a == b else "%d-%d" % (a, b) for a, b in out
    )


class ValidateRenderCompletenessPlugin(HookBaseClass):
    """Blocks publish when frames are missing or zero bytes."""

    @property
    def name(self):
        return "Validate Render Completeness"

    @property
    def description(self):
        return """
        Checks a rendered image sequence before it can be published:
        <ul>
        <li>every frame of the expected range exists on disk</li>
        <li>no frame is zero bytes</li>
        </ul>
        The expected range is the write node's own frame range when
        "use limit to range" is enabled, otherwise the script frame range.
        Pixel size / colorspace are not checked.
        """

    @property
    def icon(self):
        candidates = [
            os.path.join(self.disk_location, "icons", "review.png"),
            os.path.join(self.disk_location, os.pardir, "icons", "review.png"),
        ]
        try:
            app_dir = self.parent.disk_location
            candidates += [
                os.path.join(app_dir, "hooks", "icons", "validate.png"),
                os.path.join(app_dir, "hooks", "icons", "publish.png"),
            ]
        except Exception:
            pass
        for path in candidates:
            if os.path.exists(path):
                return path
        return ""

    @property
    def settings(self):
        return {}

    @property
    def item_filters(self):
        return ["file.image.sequence"]

    def accept(self, settings, item):
        return {"accepted": True, "checked": True}

    # ------------------------------------------------------------------ helpers
    def _expected_range(self, item):
        first = item.properties.get("first_frame")
        last = item.properties.get("last_frame")
        node = item.properties.get("sg_writenode")
        if node is not None:
            try:
                if node.knob("use_limit") and node["use_limit"].value():
                    first = int(node["first"].value())
                    last = int(node["last"].value())
            except Exception:
                self.logger.debug("Could not read frame range from write node")
        if first is None or last is None or int(last) < int(first):
            return None, None
        return int(first), int(last)

    @staticmethod
    def _frames_by_number(pattern, paths):
        """Map frame number -> path using the %0Nd pattern of the sequence."""
        m = re.search(r"%0?\d*d", pattern.replace("\\", "/"))
        if not m:
            return {}
        pattern = pattern.replace("\\", "/")
        prefix, suffix = pattern[: m.start()], pattern[m.end():]
        frames = {}
        for path in paths:
            p = path.replace("\\", "/")
            if not p.startswith(prefix):
                continue
            if suffix and not p.endswith(suffix):
                continue
            middle = p[len(prefix): len(p) - len(suffix)] if suffix else p[len(prefix):]
            if middle.lstrip("-").isdigit():
                frames[int(middle)] = path
        return frames

    def _fail(self, message, details=None):
        extra = None
        if details:
            extra = {
                "action_show_more_info": {
                    "label": "Show Details",
                    "tooltip": "Full list",
                    "text": "\n".join(details),
                }
            }
        self.logger.error(message, extra=extra)
        return False

    # ----------------------------------------------------------------- publish2
    def validate(self, settings, item):
        sequence_paths = item.properties.get("sequence_paths")
        pattern = item.properties.get("path")
        if not sequence_paths or not pattern:
            return self._fail(
                "Render completeness could not be checked: item has no "
                "'sequence_paths' / 'path'."
            )

        first, last = self._expected_range(item)
        frames = self._frames_by_number(pattern, sequence_paths)

        if first is not None and frames:
            expected = set(range(first, last + 1))
            missing = sorted(expected - set(frames))
            if missing:
                return self._fail(
                    "%d frame(s) missing from expected range %d-%d: %s"
                    % (len(missing), first, last, _compress(missing)),
                    ["%d" % f for f in missing],
                )
            extra = sorted(set(frames) - expected)
            if extra:
                self.logger.warning(
                    "%d frame(s) exist outside the expected range %d-%d "
                    "(%s) and will be part of the published sequence."
                    % (len(extra), first, last, _compress(extra))
                )
        elif first is not None:
            # could not parse frame numbers - fall back to a plain count
            expected_count = last - first + 1
            if len(sequence_paths) < expected_count:
                return self._fail(
                    "Expected at least %d frames (%d-%d), found %d."
                    % (expected_count, first, last, len(sequence_paths))
                )

        zero = [p for p in sequence_paths if os.path.getsize(p) == 0]
        if zero:
            return self._fail(
                "%d frame(s) are zero bytes (render likely failed). First: %s"
                % (len(zero), zero[0]),
                zero,
            )

        self.logger.debug(
            "Render completeness OK: %d frame(s)" % len(sequence_paths)
        )
        return True

    def publish(self, settings, item):
        pass

    def finalize(self, settings, item):
        pass
