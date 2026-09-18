import pytest

import exceptions
import services


def setup_two_tasks_with_dependency(env):
    ps = env["projects"]
    ts = env["tasks"]
    proj = ps.create_project("Alpha")
    a = ts.create_task(proj.id, title="Task A", priority="Low")
    b = ts.create_task(proj.id, title="Task B", priority="Medium")
    ts.set_dependencies(proj.id, b.id, [a.id])  # B depends on A
    return proj, a, b


def test_delete_task_blocked_by_dependents_ac11(env):
    proj, a, b = setup_two_tasks_with_dependency(env)
    ts = env["tasks"]

    with pytest.raises(exceptions.DeletionBlockedError) as ei:
        ts.delete_task(proj.id, a.id)

    err = ei.value
    # Prefer the structured dependents attribute if provided
    dependents = getattr(err, "dependents", None)
    if dependents is not None:
        assert b.id in dependents
    else:
        # Fall back to message content check
        assert b.id in str(err) or "Task B" in str(err)

    # Ensure neither task was deleted due to the block
    remaining_ids = {t.id for t in ts.list_tasks(proj.id)}
    assert a.id in remaining_ids and b.id in remaining_ids


def test_set_dependencies_reflected_in_details_ac12(env):
    proj, a, b = setup_two_tasks_with_dependency(env)
    ts = env["tasks"]

    b_fetched = ts.get_task(proj.id, b.id)
    assert a.id in b_fetched.dependencies


def test_blocked_completion_status_change_ac13(env):
    proj, a, b = setup_two_tasks_with_dependency(env)
    ts = env["tasks"]

    with pytest.raises(exceptions.BlockedCompletionError) as ei:
        ts.set_task_status(proj.id, b.id, "Done")

    err = ei.value
    blockers = getattr(err, "blocking_dependencies", None)
    if blockers is not None:
        assert a.id in blockers
    # Status must remain not Done
    b_after = ts.get_task(proj.id, b.id)
    assert b_after.status != "Done"


def test_blocked_completion_move_to_done_ac13(env):
    proj, a, b = setup_two_tasks_with_dependency(env)
    ts = env["tasks"]

    with pytest.raises(exceptions.BlockedCompletionError):
        ts.move_task_between_columns(proj.id, b.id, "Done")

    b_after = ts.get_task(proj.id, b.id)
    assert b_after.status != "Done"


def test_move_to_in_progress_allowed_ac14(env):
    proj, a, b = setup_two_tasks_with_dependency(env)
    ts = env["tasks"]

    moved = ts.set_task_status(proj.id, b.id, "In Progress")
    assert moved.status == "In Progress"


def test_circular_dependency_prevented_ac15(env):
    proj, a, b = setup_two_tasks_with_dependency(env)
    ts = env["tasks"]

    # Attempt to make A depend on B, which would create a cycle
    with pytest.raises(exceptions.DependencyCycleError):
        ts.set_dependencies(proj.id, a.id, [b.id])