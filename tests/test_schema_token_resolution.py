"""
Regression test for the "$project could not be found in ... or in any
of its parents" TankError that live folder creation raised against
core/schema/Artists/sg_projectcode.yml and
core/schema/Projects/sg_projectcode.yml.

Root cause: tk-core's FilterExpressionToken._resolve_ref_r matches a
$token against an ANCESTOR FOLDER'S LITERAL NAME (via
os.path.basename), not against entity type. Artists.yml/Projects.yml
are new project-type schema roots whose own folder is named "Artists"
/ "Projects" -- there is no folder literally named "project" anywhere
above them (that name only exists in the old, unrelated tank_name-
rooted core/schema/project/ tree). A $project token underneath them
therefore has nothing to bind to.

Requires a real, importable tk-core checkout (not vendored in this
repo) - set TK_CORE_PYTHON_PATH to <tk-core checkout>/python to run
this test; it is skipped otherwise so it doesn't become a hard CI
dependency on an external repo.
"""
import os
import sys
import pytest

TK_CORE_PATH = os.environ.get("TK_CORE_PYTHON_PATH")

pytestmark = pytest.mark.skipif(
    not TK_CORE_PATH or not os.path.isdir(TK_CORE_PATH),
    reason=(
        "Set TK_CORE_PYTHON_PATH to a tk-core checkout's python/ dir "
        "to run real folder-schema token resolution tests."
    ),
)

if TK_CORE_PATH and os.path.isdir(TK_CORE_PATH):
    sys.path.insert(0, TK_CORE_PATH)


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


def test_old_project_token_fails_under_artists_root():
    """Reproduces the exact bug seen in production folder-creation logs."""
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken
    from tank.errors import TankError

    artists_root = _make_entity_node("/config/core/schema/Artists", parent=None)
    with pytest.raises(TankError, match=r"\$project could not be found"):
        FilterExpressionToken("$project", artists_root)


def test_artists_token_resolves_under_artists_root():
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken

    artists_root = _make_entity_node("/config/core/schema/Artists", parent=None)
    tok = FilterExpressionToken("$Artists", artists_root)
    assert tok.get_entity_type() == "Project"
    assert tok.get_sg_data_key() == "Project"


def test_projects_token_resolves_under_projects_root():
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken

    projects_root = _make_entity_node("/config/core/schema/Projects", parent=None)
    tok = FilterExpressionToken("$Projects", projects_root)
    assert tok.get_entity_type() == "Project"


def test_old_project_tree_token_unaffected():
    """Regression guard: the pre-existing project/ tree must still work."""
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken

    project_root = _make_entity_node("/config/core/schema/project", parent=None)
    tok = FilterExpressionToken("$project", project_root)
    assert tok.get_entity_type() == "Project"


def test_grandchild_can_still_reach_artists_token():
    from tank.folder.folder_types.expression_tokens import FilterExpressionToken

    artists_root = _make_entity_node("/config/core/schema/Artists", parent=None)
    sg_projectcode_node = _make_entity_node(
        "/config/core/schema/Artists/sg_projectcode", parent=artists_root
    )
    tok = FilterExpressionToken("$Artists", sg_projectcode_node)
    assert tok.get_entity_type() == "Project"


def test_schema_files_use_fixed_token_not_project():
    """
    Static guard against regressing back to $project in these two
    files even without a tk-core checkout available - this part always
    runs.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel_path, expected_token in [
        ("core/schema/Artists/sg_projectcode.yml", "$Artists"),
        ("core/schema/Projects/sg_projectcode.yml", "$Projects"),
    ]:
        full_path = os.path.join(repo_root, rel_path)
        with open(full_path) as f:
            content = f.read()
        assert expected_token in content, (
            f"{rel_path} should filter on {expected_token}, not $project"
        )
        assert '"values": [ "$project" ]' not in content, (
            f"{rel_path} still has the buggy unresolvable $project token"
        )
