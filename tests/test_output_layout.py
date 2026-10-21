"""
The studio's render / review folder layout: everything a write node renders
goes to <shot>/<Step>/Output/..., not into the Nuke/ work area.

  Artists/<Seq>/<Shot>/<Step>/Output/exr/<Shot>_<Step>_OS_v###.####.exr
  Artists/<Seq>/<Shot>/<Step>/Output/mov/HD|4K/<Shot>_<step>_OS_v###.mov
"""
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
SCHEMA = CORE / "schema" / "project"
STEP_DIRS = ("Artists", "Publish")


def _templates():
    paths = {}
    for name in ("common.yml", "tk-nuke.yml"):
        data = yaml.safe_load((CORE / "templates" / name).read_text())
        paths.update(data.get("paths", {}))

    def definition(name):
        d = paths[name]
        d = d if isinstance(d, str) else d["definition"]
        while "@" in d:
            ref = re.search(r"@(\w+)", d).group(1)
            r = paths[ref]
            d = d.replace("@" + ref, r if isinstance(r, str) else r["definition"])
        return d

    return definition


def test_exr_paths_match_the_studio_layout():
    d = _templates()
    assert d("nuke_shot_render") == (
        "Artists/{Sequence}/{Shot}/{Step}/Output/exr/{Shot}_{Step}_OS_v{version}.{SEQ}.exr"
    )
    assert d("nuke_shot_render_pub") == (
        "Publish/{Sequence}/{Shot}/{Step}/Output/exr/{Shot}_{Step}_OS_v{version}.{SEQ}.exr"
    )


def test_mov_paths_are_sorted_by_size():
    d = _templates()
    assert d("nuke_shot_write_movie").endswith(
        "/{Step}/Output/mov/{mov_size}/{Shot}_{step_lower}_OS_v{version}.mov"
    )
    assert d("nuke_shot_write_movie_pub").startswith("Publish/")
    assert "/Output/mov/review/" in d("nuke_shot_render_movie")


def test_nothing_renders_into_the_nuke_work_area_any_more():
    d = _templates()
    for name in ("nuke_shot_render", "nuke_shot_render_pub", "nuke_shot_write_movie",
                 "nuke_shot_write_movie_pub", "nuke_shot_render_movie",
                 "nuke_shot_render_movie_pub"):
        assert "/Nuke/" not in d(name) and "renders/" not in d(name), name


def test_mov_size_key_allows_exactly_the_schema_folders():
    keys = yaml.safe_load((CORE / "templates" / "common.yml").read_text())["keys"]
    sizes = keys["mov_size"]["choices"]
    for tree in STEP_DIRS:
        out = SCHEMA / tree / "sequence" / "shot" / "step" / "Output"
        for size in sizes:
            assert (out / "mov" / (size + ".yml")).is_file(), (tree, size)


def test_every_output_folder_a_template_writes_to_is_in_the_schema():
    for tree in STEP_DIRS:
        out = SCHEMA / tree / "sequence" / "shot" / "step" / "Output"
        for folder in ("exr", "mov", "mov/HD", "mov/4K", "mov/review"):
            yml = out / (folder + ".yml")
            assert yml.is_file(), yml
            assert yaml.safe_load(yml.read_text())["type"] == "static"
            assert (out / folder).parent.is_dir()


def test_output_is_created_together_with_the_nuke_work_area():
    for tree in STEP_DIRS:
        step = SCHEMA / tree / "sequence" / "shot" / "step"
        out = yaml.safe_load((step / "Output.yml").read_text())
        inner = yaml.safe_load((step / "Nuke" / "step.yml").read_text())
        assert out["defer_creation"] == inner["defer_creation"] == "tk-nuke"
