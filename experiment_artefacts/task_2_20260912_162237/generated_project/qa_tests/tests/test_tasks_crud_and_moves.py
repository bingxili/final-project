import services


def test_create_task_ac6(env):
    ps = env["projects"]
    ts = env["tasks"]

    proj = ps.create_project("Alpha")
    task = ts.create_task(proj.id, title="Write spec", priority="High", tags=["docs"])

    assert task.title == "Write spec"
    assert task.priority == "High"
    assert "docs" in task.tags
    assert task.due_date is None
    # Defaults to To Do if no status chosen
    assert task.status == "To Do"


def test_edit_task_ac7(env):
    ps = env["projects"]
    ts = env["tasks"]

    proj = ps.create_project("Alpha")
    task = ts.create_task(proj.id, title="Edit me", priority="Medium", tags=["docs"])

    edited = ts.edit_task(
        proj.id,
        task.id,
        description="Updated description",
        priority="High",
        tags=["docs", "review"],
        due_date="2026-09-20",
        due_date_set=True,
    )

    assert edited.description == "Updated description"
    assert edited.priority == "High"
    assert "review" in edited.tags
    assert str(edited.due_date) == "2026-09-20"


def test_move_task_to_in_progress_ac8(env):
    ps = env["projects"]
    ts = env["tasks"]

    proj = ps.create_project("Alpha")
    task = ts.create_task(proj.id, title="Move me", priority="Low")

    moved = ts.move_task_between_columns(proj.id, task.id, "In Progress")
    assert moved.status == "In Progress"


def test_move_task_back_to_todo_ac9(env):
    ps = env["projects"]
    ts = env["tasks"]

    proj = ps.create_project("Alpha")
    task = ts.create_task(proj.id, title="Back and forth", priority="Medium")
    ts.move_task_between_columns(proj.id, task.id, "In Progress")

    moved_back = ts.move_task_between_columns(proj.id, task.id, "To Do")
    assert moved_back.status == "To Do"


def test_delete_task_persists_ac10(tmp_path):
    # Setup
    import persistence

    repo = persistence.JsonRepository(root_dir=tmp_path, autosave=False)
    state = repo.load()
    ps = services.ProjectService(state, repo)
    ts = services.TaskService(state, repo)

    proj = ps.create_project("Alpha")
    task = ts.create_task(proj.id, title="Temp", priority="Low")

    # Delete and save
    ts.delete_task(proj.id, task.id)
    repo.save(state)

    # Reload
    repo2 = persistence.JsonRepository(root_dir=tmp_path, autosave=False)
    state2 = repo2.load()
    ps2 = services.ProjectService(state2, repo2)
    ts2 = services.TaskService(state2, repo2)
    proj2 = next(p for p in ps2.list_projects() if p.id == proj.id)

    tasks_after = ts2.list_tasks(proj2.id)
    assert all(t.id != task.id for t in tasks_after)
    assert tasks_after == []