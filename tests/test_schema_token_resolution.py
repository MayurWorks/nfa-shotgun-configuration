"""
Regression test for the "$project could not be found in ... or in any
of its parents" TankError that live folder creation raised against the
Artists/Projects schema trees, twice: first against
core/schema/Artists/sg_projectcode.yml and
core/schema/Projects/sg_projectcode.yml (fixed in an earlier commit),
then again one level deeper against
core/schema/Artists/sg_projectcode/sequence.yml and
core/schema/Projects/sg_projectcode/Plates/sequence.yml (fixed in this
commit) - the first fix only updated the direct child of the new
Artists/Projects roots and missed that the grandchild had the exact
same problem.

Root cause: tk-core's FilterExpressionToken._resolve_ref_r matches a
$token against an ANCESTOR FOLDER'S LITERAL NAME (via
os.path.basename), not against entity type, walking up as many levels
as needed. Artists.yml/Projects.yml are project-type schema roots whose
own folder is named "Artists"/"Projects" -- there is no folder
literally named "project" anywhere above ANY descendant of them (that
name only exists in the old, unrelated tank_name-rooted
core/schema/project/ tree). A $project token anywhere in either tree,
at any depth, has nothing to bind to and fails with this TankError.

test_no_project_token_anywhere_in_artists_or_projects_trees (below) is
a static, dependency-free file-content sweep across the WHOLE Artists/
and Projects/ trees (not a fixed list of two files) specifically so a
third occurrence at a still-deeper level can't slip through the same
way the grandchild did here - it always runs, with no environment
requirement, unlike the tk-core-backed tests in this file which need a
real tk-core checkout (set TK_CORE_PYTHON_PATH to <tk-core
checkout>/python) and are skipped otherwise.
"""
import os
import sys
import glob
import pytest

TK_CORE_PATH = os.environ.get("TK_CORE_PYTHON_PATH")
_TK_CORE_AVAILABLE = bool(TK_CORE_PATH and os.path.isdir(TK_CORE_PATH))

if _TK_CORE_AVAILABLE:
    sys.path.insert(0, TK_CORE_PATH)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_requires_tk_core = pytest.mark.skipif(
    not _TK_CORE_AVAILABLE,
    reason=(
        "Set TK_CORE_PYTHON_PATH to a tk-core checkout's python/ dir "
        "to run real folder-schema token resolution tests."
    ),
)


def _make_entity_node(full_path, parent, entity_type="Project"):
    from tank.folder.folder_types.entity import Entity

    return Entity(
        tk=None,
        parent=parent,
        full_path=full_path,
        metadata={},
        entity_type=entity_type,
        field_name_expression="sg_projectcode",
        filters={"logical_operator": "and", "conditions": []},
        create_with_parent=False,
    )


def test_no_project_token_anywhere_in_artists_or_projects_trees():
    """
    Always runs, no tk-core needed: sweeps every .yml file under
    core/schema/Artists/ and core/schema/Projects/ (any depth) for the
    literal, unresolvable "$project" token in a filter value. This is
    the check that would have caught the grandchild regression this
    commit fixes -- the previous version of this test only checked two
    specific file paths by name.
    """
    offenders = []
    for tree in ("Artists", "Projects"):
        pattern = os.path.join(REPO_ROOT, "core", "schema", tree, "**", "*.yml")
        for path in glob.glob(pattern, recursive=True):
            with open(path) as f:
                content = f.read()
            if '"$project"' in content or "'$project'" in content:
                offenders.append(os.path.relpath(path, REPO_ROOT))
    assert not offenders, (
        "found literal $project token (unresolvable under the "
        "Artists/Projects schema roots -- must be $Artists/$Projects "
        "instead) in: %s" % offenders
    )


def test_grandchild_files_use_correct_root_token():
    """Specific regression guard for the two files this commit fixes."""
    for rel_path, expected_token in [
        ("core/schema/Artists/sg_projectcode/sequence.yml", "$Artists"),
        ("core/schema/Projects/sg_projectcode/Plates/sequence.yml", "$Projects"),
    ]:
        full_path = os.path.join(REPO_ROOT, rel_path)
        with open(full_path) as f:
            content = f.read()
        assert expected_token in content, (
            "%s should filter on %s" % (rel_path, expected_token)
        )


@_requires_tk_core
def test_old_project_token_fails_under_artists_root():
    """Reproduces the exact bug seen in production folder-creation logs."""
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken
    from tank.errors import TankError

    artists_root = _make_entity_node("/config/core/schema/Artists", parent=None)
    with pytest.raises(TankError, match=r"\$project could not be found"):
        FilterExpressionToken("$project", artists_root)


@_requires_tk_core
def test_artists_token_resolves_under_artists_root():
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken

    artists_root = _make_entity_node("/config/core/schema/Artists", parent=None)
    tok = FilterExpressionToken("$Artists", artists_root)
    assert tok.get_entity_type() == "Project"
    assert tok.get_sg_data_key() == "Project"


@_requires_tk_core
def test_projects_token_resolves_under_projects_root():
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken

    projects_root = _make_entity_node("/config/core/schema/Projects", parent=None)
    tok = FilterExpressionToken("$Projects", projects_root)
    assert tok.get_entity_type() == "Project"


@_requires_tk_core
def test_old_project_tree_token_unaffected():
    """Regression guard: the pre-existing project/ tree must still work."""
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken

    project_root = _make_entity_node("/config/core/schema/project", parent=None)
    tok = FilterExpressionToken("$project", project_root)
    assert tok.get_entity_type() == "Project"


@_requires_tk_core
def test_grandchild_can_still_reach_artists_token():
    """
    The real regression this commit fixes, exercised against actual
    tk-core token resolution (not just a static string check): a node
    TWO levels below the Artists root must still resolve $Artists by
    walking up past its immediate parent.
    """
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken

    artists_root = _make_entity_node("/config/core/schema/Artists", parent=None)
    sg_projectcode_node = _make_entity_node(
        "/config/core/schema/Artists/sg_projectcode", parent=artists_root
    )
    sequence_node = _make_entity_node(
        "/config/core/schema/Artists/sg_projectcode/sequence",
        parent=sg_projectcode_node,
        entity_type="Sequence",
    )
    tok = FilterExpressionToken("$Artists", sequence_node)
    assert tok.get_entity_type() == "Project"
