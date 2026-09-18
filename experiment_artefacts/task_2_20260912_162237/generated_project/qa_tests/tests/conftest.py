import pathlib
import pytest

import models
import persistence
import services


@pytest.fixture
def env(tmp_path: pathlib.Path):
    # Create a fresh repository in a temporary directory and return constructed services.
    repo = persistence.JsonRepository(root_dir=tmp_path, autosave=False)
    state = repo.load()
    project_service = services.ProjectService(state, repo)
    task_service = services.TaskService(state, repo)
    return {"repo": repo, "state": state, "projects": project_service, "tasks": task_service}