import datetime

import pytest

import services
import validation


def test_invalid_due_date_rejected_and_unchanged_ac22(env):
    ps = env["projects"]
    ts = env["tasks"]

    proj = ps.create_project("Alpha")
    t = ts.create_task(proj.id, title="With due", priority="Medium", due_date="2026-09-10")
    assert str(t.due_date) == "2026-09-10"

    # Attempt to set an invalid due date; expect rejection and previous value preserved
    with pytest.raises((ValueError,)):
        ts.edit_task(proj.id, t.id, due_date="2026-13-40", due_date_set=True)

    t_after = ts.get_task(proj.id, t.id)
    assert str(t_after.due_date) == "2026-09-10"


def test_parse_due_date_invalid_ac22_validation():
    with pytest.raises(ValueError):
        validation.parse_due_date("2026-13-40")


def test_invalid_priority_rejected_and_unchanged_ac23(env):
    ps = env["projects"]
    ts = env["tasks"]

    proj = ps.create_project("Alpha")
    t = ts.create_task(proj.id, title="Priority test", priority="Medium")
    assert t.priority == "Medium"

    with pytest.raises((ValueError,)):
        ts.edit_task(proj.id, t.id, priority="Critical")

    t_after = ts.get_task(proj.id, t.id)
    assert t_after.priority == "Medium"


def test_validate_priority_invalid_ac23_validation():
    with pytest.raises(ValueError):
        validation.validate_priority("Critical")


def test_add_remove_tags_ac24(env):
    ps = env["projects"]
    ts = env["tasks"]

    proj = ps.create_project("Alpha")
    t = ts.create_task(proj.id, title="Tag me", priority="Low")
    assert t.tags == [] or t.tags is None or len(t.tags) == 0

    t_with_tag = ts.add_tag(proj.id, t.id, "backend")
    assert "backend" in t_with_tag.tags

    t_without_tag = ts.remove_tag(proj.id, t.id, "backend")
    assert "backend" not in t_without_tag.tags