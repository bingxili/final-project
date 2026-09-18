import pathlib

import models
import services
import persistence


def test_create_project_ac1(env):
    ps = env["projects"]
    ts = env["tasks"]

    proj = ps.create_project("Alpha")
    assert isinstance(proj, models.Project)
    assert proj.name == "Alpha"

    # The board columns are a UI concern; here we assert the project is created empty.
    assert ts.list_tasks(proj.id) == []


def test_switch_active_project_ac2(env):
    ps = env["projects"]
    ts = env["tasks"]
    state = env["state"]

    alpha = ps.create_project("Alpha")
    beta = ps.create_project("Beta")

    t_alpha = ts.create_task(alpha.id, title="A1", priority="Low")
    t_beta = ts.create_task(beta.id, title="B1", priority="High")

    # Switch active project to Beta
    active = ps.set_active_project(beta.id)
    assert active.id == beta.id
    assert state.get_active_project() is active

    # Ensure tasks are isolated per project
    alpha_tasks = ts.list_tasks(alpha.id)
    beta_tasks = ts.list_tasks(beta.id)
    assert {t.id for t in alpha_tasks} == {t_alpha.id}
    assert {t.id for t in beta_tasks} == {t_beta.id}


def test_rename_project_ac3(env):
    ps = env["projects"]
    ts = env["tasks"]

    proj = ps.create_project("Alpha")
    t1 = ts.create_task(proj.id, title="Task1", priority="Medium")
    t2 = ts.create_task(proj.id, title="Task2", priority="High")

    renamed = ps.rename_project(proj.id, "Gamma")
    assert renamed.id == proj.id
    assert renamed.name == "Gamma"

    # Tasks remain unchanged
    titles = sorted(t.title for t in ts.list_tasks(proj.id))
    assert titles == ["Task1", "Task2"]


def test_delete_project_ac4(env):
    ps = env["projects"]
    ts = env["tasks"]

    alpha = ps.create_project("Alpha")
    beta = ps.create_project("Beta")
    ts.create_task(alpha.id, title="A1", priority="Low")
    ts.create_task(beta.id, title="B1", priority="High")

    # Delete Alpha (UI confirmation is not part of the services contract)
    ps.delete_project(alpha.id)

    names = [p.name for p in ps.list_projects()]
    assert "Alpha" not in names
    assert "Beta" in names


def test_persistence_ac5(tmp_path):
    # Build initial services
    repo = persistence.JsonRepository(root_dir=tmp_path, autosave=False)
    state = repo.load()
    ps = services.ProjectService(state, repo)
    ts = services.TaskService(state, repo)

    proj = ps.create_project("Alpha")
    ps.set_active_project(proj.id)
    created = ts.create_task(proj.id, title="Persist me", priority="High", tags=["docs"])

    # Explicit save to simulate persisted app state
    repo.save(state)

    # "Restart": new repo/services loading from the same directory
    repo2 = persistence.JsonRepository(root_dir=tmp_path, autosave=False)
    state2 = repo2.load()
    ps2 = services.ProjectService(state2, repo2)
    ts2 = services.TaskService(state2, repo2)

    # Verify project and task persisted with fields unchanged
    projects = ps2.list_projects()
    assert any(p.name == "Alpha" for p in projects)
    # Find the project by id (should be the same id)
    project2 = next(p for p in projects if p.id == proj.id)
    tasks2 = ts2.list_tasks(project2.id)
    assert len(tasks2) == 1
    t2 = tasks2[0]
    assert t2.title == "Persist me"
    assert "docs" in t2.tags
    assert t2.priority == "High"
    assert t2.due_date is None