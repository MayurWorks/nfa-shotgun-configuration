from conftest import HOOKS, load_module

pc = load_module("pipeline_checks", HOOKS / "pipeline_checks.py")


def _levels(findings):
    return sorted(f.level for f in findings)


class TestLocalPaths:
    def test_home_and_tmp_are_local(self):
        assert pc.is_local_path("/home/mayur/shot.%04d.exr")
        assert pc.is_local_path("/tmp/x.exr")
        assert pc.is_local_path("C:\\Users\\a\\x.exr")

    def test_project_root_is_never_local(self):
        assert not pc.is_local_path("/jobs/SlateX/Artists/a.exr", ["/jobs/SlateX"])
        # even when the root itself looks like a "local" prefix
        assert not pc.is_local_path("/home/studio/jobs/a.exr", ["/home/studio/jobs"])

    def test_empty_and_tcl_expressions_are_not_judged(self):
        assert not pc.is_local_path("")
        assert not pc.is_local_path("[value root.name]/x.exr")

    def test_root_prefix_must_match_whole_segment(self):
        assert pc.is_local_path("/home/studio/jobsX/a.exr", ["/home/studio/jobs"])


class TestSettings:
    ACTUAL = dict(fps=24.0, first_frame=1001, last_frame=1085, width=1920, height=1080,
                  ocio_config="aces_1.2", working_colorspace="ACES - ACEScg")

    def test_matching_script_has_no_findings(self):
        assert pc.check_settings(self.ACTUAL, dict(self.ACTUAL)) == []

    def test_nothing_expected_nothing_checked(self):
        assert pc.check_settings(self.ACTUAL, {}) == []

    def test_fps_mismatch_is_error(self):
        f = pc.check_settings(self.ACTUAL, {"fps": 25.0})
        assert _levels(f) == ["error"] and "fps" in f[0].message

    def test_fps_float_tolerance(self):
        assert pc.check_settings({"fps": 23.976}, {"fps": 23.9760001}) == []

    def test_range_mismatch(self):
        f = pc.check_settings(self.ACTUAL, {"first_frame": 1001, "last_frame": 1100})
        assert len(f) == 1 and "last frame" in f[0].message

    def test_format_mismatch(self):
        f = pc.check_settings(self.ACTUAL, {"width": 2048, "height": 858})
        assert len(f) == 1 and "format" in f[0].message

    def test_ocio_name_match_ignores_punctuation(self):
        assert pc.check_settings({"ocio_config": "aces_1.2"}, {"ocio_config": "ACES 1.2"}) == []
        assert pc.check_settings({"ocio_config": "nuke-default"}, {"ocio_config": "aces_1.2"})

    def test_working_space_mismatch_is_only_warning(self):
        f = pc.check_settings({"working_colorspace": "linear"}, {"working_colorspace": "ACES - ACEScg"})
        assert _levels(f) == ["warning"]


class TestNodes:
    def n(self, **kw):
        base = dict(name="Read1", file="/jobs/a.%04d.exr", disabled=False, exists=True, sg_managed=False)
        base["class"] = kw.pop("cls", "Read")
        base.update(kw)
        return base

    def test_clean_script(self):
        assert pc.check_nodes([self.n()], ["/jobs"]) == []

    def test_missing_read_files(self):
        f = pc.check_nodes([self.n(exists=False)], ["/jobs"])
        assert _levels(f) == ["error"] and f[0].details == ["Read1"]

    def test_disabled_missing_read_ignored(self):
        assert pc.check_nodes([self.n(exists=False, disabled=True)], ["/jobs"]) == []

    def test_empty_path(self):
        f = pc.check_nodes([self.n(file="", exists=None)], ["/jobs"])
        assert len(f) == 1 and "no file path" in f[0].message

    def test_local_path_on_write(self):
        f = pc.check_nodes([self.n(cls="Write", name="Write1", file="/tmp/out.exr", exists=None)], ["/jobs"])
        assert _levels(f) == ["error"] and "local disk" in f[0].message

    def test_disabled_pipeline_write_is_warning(self):
        f = pc.check_nodes([self.n(cls="Write", disabled=True, sg_managed=True, exists=None)], ["/jobs"])
        assert _levels(f) == ["warning"]

    def test_disabled_user_write_is_fine(self):
        assert pc.check_nodes([self.n(cls="Write", disabled=True, exists=None)], ["/jobs"]) == []

    def test_summarise(self):
        errors, warnings = pc.summarise([pc.Finding("error", "a"), pc.Finding("warning", "b")])
        assert len(errors) == 1 and len(warnings) == 1
