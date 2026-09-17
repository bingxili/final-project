import datetime
import tempfile
import os

import models
import persistence
import services
from exceptions import BlockedCompletionError, DependencyCycleError, DeletionBlockedError
from filters import filter_tasks
from stats import compute_statistics


def setup_repo_state():
    tmpdir = tempfile.TemporaryDirectory()
    repo = persistence.JsonRepository(root_dir=tmpdir.name, autosave=False)
    state = models.AppState()
    proj_svc = services.ProjectService(state, repo)
    task_svc = services.TaskService(state, repo)
    return tmpdir, repo, state, proj_svc, task_svc


def test_project_crud_and_persistence_roundtrip():
    tmpdir, repo, state, proj_svc, task_svc = setup_repo_state()

    # Create project
    p = proj_svc.create_project("Alpha")
    assert p.name == "Alpha"
    assert state.active_project_id == p.id
    # Rename
    proj_svc.rename_project(p.id, "Gamma")
    assert state.projects[p.id].name == "Gamma"

    # Add a task
    t = task_svc.create_task(p.id, title="Write spec", priority="High", tags=["docs"])
    assert t.status == "To Do"
    assert "docs" in t.tags

    # Save explicitly and reload
    repo.save(state)
    loaded = repo.load()
    assert p.id in loaded.projects
    assert any(task.title == "Write spec" for task in loaded.projects[p.id].tasks.values())

    # Delete project
    proj_svc.delete_project(p.id)
    assert p.id not in state.projects

    # Save/load again
    repo.save(state)
    loaded2 = repo.load()
    assert p.id not in loaded2.projects


def test_dependencies_and_blocked_completion():
    tmpdir, repo, state, proj_svc, task_svc = setup_repo_state()
    p = proj_svc.create_project("Alpha")
    a = task_svc.create_task(p.id, "Task A", "Medium")
    b = task_svc.create_task(p.id, "Task B", "Medium")
    # Set B depends on A
    task_svc.set_dependencies(p.id, b.id, [a.id])
    assert a.id in state.projects[p.id].tasks[b.id].dependencies
    # Cannot complete B until A is done
    try:
        task_svc.set_task_status(p.id, b.id, "Done")
        assert False, "Expected BlockedCompletionError"
    except BlockedCompletionError as e:
        assert a.id in e.blocking_dependencies

    # Completing A allows B to complete
    task_svc.set_task_status(p.id, a.id, "Done")
    b2 = task_svc.set_task_status(p.id, b.id, "Done")
    assert b2.status == "Done"

    # Cycle prevention: cannot set A depends on B (would cycle)
    try:
        task_svc.set_dependencies(p.id, a.id, [b.id])
        assert False, "Expected DependencyCycleError"
    except DependencyCycleError:
        pass


def test_delete_blocked_by_dependents():
    tmpdir, repo, state, proj_svc, task_svc = setup_repo_state()
    p = proj_svc.create_project("Alpha")
    a = task_svc.create_task(p.id, "A", "Low")
    b = task_svc.create_task(p.id, "B", "High")
    task_svc.set_dependencies(p.id, b.id, [a.id])
    # Deleting A should be blocked
    try:
        task_svc.delete_task(p.id, a.id)
        assert False, "Expected DeletionBlockedError"
    except DeletionBlockedError as e:
        assert b.id in e.dependents

    # Deleting B first then A works
    task_svc.delete_task(p.id, b.id)
    task_svc.delete_task(p.id, a.id)
    assert len(state.projects[p.id].tasks) == 0


def test_filtering_and_stats():
    tmpdir, repo, state, proj_svc, task_svc = setup_repo_state()
    p = proj_svc.create_project("Alpha")
    t1 = task_svc.create_task(p.id, "UI task", "High", tags=["UI"], status="In Progress", due_date="2026-09-10")
    t2 = task_svc.create_task(p.id, "Backend task", "Medium", tags=["Backend"], status="To Do", due_date="2026-09-20")
    t3 = task_svc.create_task(p.id, "Docs task", "Low", tags=["Docs"], status="Done")
    all_tasks = list(state.projects[p.id].tasks.values())

    # Filter status [In Progress] AND priority [High]
    filtered = filter_tasks(all_tasks, status={"In Progress"}, priorities={"High"})
    assert len(filtered) == 1 and filtered[0].id == t1.id

    # Filter tags any-of with case-insensitive
    filtered = filter_tasks(all_tasks, tags_any_of={"ui", "api"})
    assert len(filtered) == 1 and filtered[0].id == t1.id

    # Filter due date inclusive range
    filtered = filter_tasks(all_tasks, due_date_start="2026-09-01", due_date_end="2026-09-15")
    assert len(filtered) == 1 and filtered[0].id == t1.id

    # Stats - set today to 2026-09-15 so t1 overdue? No, due 10 < 15 and not done => overdue=1
    stats = compute_statistics(state.projects[p.id], today=datetime.date(2026, 9, 15))
    assert stats["todo_count"] == 1
    assert stats["in_progress_count"] == 1
    assert stats["done_count"] == 1
    assert stats["overdue_count"] == 1
    assert stats["completion_percent"] == round((1 / 3) * 100)
