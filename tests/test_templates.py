"""
Standalone tests for this Toolkit config's path templates
(core/templates.yml + core/templates/*.yml).

Does NOT require sgtk/tk-core to run -- re-implements the same @alias
expansion Toolkit's own Template class performs, so these tests can run
in any plain Python environment (CI, a laptop with no Nuke/ShotGrid
install) and still catch the two bug classes that have hit this repo
before:
  1. duplicate (root_name, resolved_definition) across different
     template names (Toolkit refuses to load the config at all if this
     happens)
  2. path templates that don't resolve to the structure the studio
     actually requires

Run with: python3 -m pytest tests/test_templates.py -v
       or: python3 tests/test_templates.py   (falls back to plain asserts)
"""
import os
import re
import sys
import glob

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required to run these tests: pip install pyyaml")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _load_all_templates():
    """Loads and merges every path/key/string template across the repo's
    includes chain, exactly like Toolkit's TemplatePathTree does."""
    manifest = _load_yaml(os.path.join(REPO_ROOT, "core/templates.yml"))
    keys, paths, path_roots, strings = {}, {}, {}, {}

    for inc in manifest.get("includes", []):
        inc_path = os.path.normpath(os.path.join(REPO_ROOT, "core", inc))
        assert os.path.isfile(inc_path), "missing include: %s" % inc_path
        data = _load_yaml(inc_path)
        for k, v in (data.get("keys") or {}).items():
            keys[k] = v
        for name, v in (data.get("paths") or {}).items():
            if isinstance(v, str):
                definition, root_name = v, "primary"
            elif isinstance(v, dict):
                definition = v.get("definition", v)
                root_name = v.get("root_name", "primary")
            else:
                definition, root_name = str(v), "primary"
            assert name not in paths, "duplicate template name: %s" % name
            paths[name] = definition
            path_roots[name] = root_name
        for name, v in (data.get("strings") or {}).items():
            strings[name] = v

    return keys, paths, path_roots, strings


_ALIAS_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")


def _expand(paths, name, _seen=None):
    _seen = _seen or set()
    assert name not in _seen, "circular alias: %s" % name
    _seen = _seen | {name}
    definition = paths.get(name)
    assert definition is not None, "undefined alias reference: %s" % name
    return _ALIAS_RE.sub(lambda m: _expand(paths, m.group(1), _seen), definition)


class TestTemplateResolution:
    @classmethod
    def setup_class(cls):
        cls.keys, cls.paths, cls.path_roots, cls.strings = _load_all_templates()
        cls.resolved = {name: _expand(cls.paths, name) for name in cls.paths}

    def test_no_duplicate_resolved_paths(self):
        """Toolkit refuses to load the config if two templates resolve to
        the identical (root_name, path) -- this is the exact bug class
        that has recurred multiple times in this repo's history."""
        seen = {}
        dupes = []
        for name, path in self.resolved.items():
            key = (self.path_roots[name], path)
            if key in seen:
                dupes.append((seen[key], name, key))
            else:
                seen[key] = name
        assert not dupes, "duplicate resolved paths found: %s" % dupes

    def test_all_referenced_keys_are_defined(self):
        key_re = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")
        missing = set()
        for name, path in self.resolved.items():
            for k in key_re.findall(path):
                if k not in self.keys and k != "SEQ":
                    missing.add((name, k))
        assert not missing, "templates reference undefined keys: %s" % missing

    def test_nuke_shot_work_matches_required_structure(self):
        """The exact example from the task spec:
        /jobs/SlateX/Artists/str/EP_2/STRM_E2_0010/RTO/Nuke/RTO/STRM_E2_0010_RTO_v006.nk
        i.e. Artists/<project_code>/<sequence>/<shot>/<step>/Nuke/<step>/..."""
        definition = self.resolved["nuke_shot_work"]
        resolved_path = definition.format(
            Projectcode="str", Sequence="EP_2", Shot="STRM_E2_0010",
            Step="RTO", version="006",
        )
        assert resolved_path == (
            "Artists/str/EP_2/STRM_E2_0010/RTO/Nuke/RTO/STRM_E2_0010_RTO_v006.nk"
        )
        # project-code folder must come AFTER Artists, not before it
        assert resolved_path.startswith("Artists/str/")

    def test_hiero_copy_path_matches_required_structure(self):
        """The exact example from the task spec:
        /jobs/SlateX/Projects/str/Plates/EP_2/STRM_E2_0010/p001/exr/str_scEP_2_STRM_E2_0010_plate_p001.%04d.exr"""
        definition = self.resolved["hiero_copy_path"]
        resolved_path = definition.format(
            Projectcode="str", Sequence="EP_2", Shot="STRM_E2_0010",
            version="001", fileext="exr", SEQ="%04d",
        )
        assert resolved_path == (
            "Projects/str/Plates/EP_2/STRM_E2_0010/p001/exr/"
            "str_scEP_2_STRM_E2_0010_plate_p001.%04d.exr"
        )
        assert resolved_path.startswith("Projects/str/")

    def test_shot_plate_matches_required_structure(self):
        definition = self.resolved["shot_plate"]
        resolved_path = definition.format(
            Projectcode="str", Sequence="EP_2", Shot="STRM_E2_0010", SEQ="1001",
        )
        assert resolved_path.startswith("Projects/str/Plates/EP_2/STRM_E2_0010/")

    def test_different_project_codes_produce_different_roots(self):
        """A second, different project's code produces a structurally
        parallel but distinct path -- not hardcoded to 'str'."""
        definition = self.resolved["nuke_shot_work"]
        for code in ("str", "abc", "PROJ99"):
            resolved_path = definition.format(
                Projectcode=code, Sequence="EP_9", Shot="X_0020",
                Step="Comp", version="001",
            )
            assert resolved_path == (
                "Artists/%s/EP_9/X_0020/Comp/Nuke/Comp/X_0020_Comp_v001.nk" % code
            )

    def test_different_shots_and_departments(self):
        definition = self.resolved["nuke_shot_work"]
        cases = [
            ("EP_1", "STRM_E1_0005", "Paint"),
            ("EP_3", "STRM_E3_0120", "Precomp"),
            ("SEQ_A", "STRM_SEQA_0010", "Roto"),
        ]
        for sequence, shot, step in cases:
            resolved_path = definition.format(
                Projectcode="str", Sequence=sequence, Shot=shot,
                Step=step, version="001",
            )
            assert resolved_path == (
                "Artists/str/%s/%s/%s/Nuke/%s/%s_%s_v001.nk"
                % (sequence, shot, step, step, shot, step)
            )

    def test_publish_tree_unaffected_by_artists_projects_change(self):
        """Publish/ still resolves under the tank_name project root (out
        of scope for this fix) and must NOT have gained a {Projectcode}
        folder segment -- tank_name already disambiguates it there."""
        definition = self.resolved["nuke_shot_publish"]
        assert definition == "Publish/{Sequence}/{Shot}/{Step}/Nuke/{Step}/{Shot}_{Step}_v{version}.nk"
        assert "{Projectcode}" not in definition

    def test_delivery_path_matches_required_structure(self):
        definition = self.resolved["shot_delivery"]
        assert definition.startswith("Projects/{Projectcode}/Delivery/")


if __name__ == "__main__":
    # Minimal runner for environments without pytest installed.
    t = TestTemplateResolution()
    t.setup_class()
    failures = []
    for name in dir(t):
        if name.startswith("test_"):
            try:
                getattr(t, name)()
                print("PASS:", name)
            except AssertionError as e:
                failures.append((name, str(e)))
                print("FAIL:", name, "-", e)
    if failures:
        print("\n%d failure(s)" % len(failures))
        sys.exit(1)
    print("\nAll tests passed.")
