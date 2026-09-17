from __future__ import annotations

import uuid
from typing import Optional, List, Set

import datetime

import models
import persistence
import validation
from exceptions import DependencyCycleError, BlockedCompletionError, DeletionBlockedError


class ProjectService:
    def __init__(self, state: models.AppState, repo: persistence.JsonRepository) -> None:
        self.state = state
        self.repo = repo

    def create_project(self, name: str) -> models.Project:
        name_s = (name or "").strip()
        if not name_s:
            raise ValueError("Project name must be non-empty.")
        pid = str(uuid.uuid4())
        project = models.Project(id=pid, name=name_s)
        self.state.projects[pid] = project
        # Set active project to the new one
        self.state.active_project_id = pid
        self.repo.save_debounced(self.state)
        return project

    def list_projects(self) -> list[models.Project]:
        return list(self.state.projects.values())

    def set_active_project(self, project_id: str) -> models.Project:
        if project_id not in self.state.projects:
            raise KeyError("Project not found")
        self.state.set_active_project(project_id)
        self.repo.save_debounced(self.state)
        return self.state.projects[project_id]

    def rename_project(self, project_id: str, new_name: str) -> models.Project:
        if project_id not in self.state.projects:
            raise KeyError("Project not found")
        new_name_s = (new_name or "").strip()
        if not new_name_s:
            raise ValueError("Project name must be non-empty.")
        proj = self.state.projects[project_id]
        proj.name = new_name_s
        self.repo.save_debounced(self.state)
        return proj

    def delete_project(self, project_id: str) -> None:
        if project_id not in self.state.projects:
            raise KeyError("Project not found")
        del self.state.projects[project_id]
        if self.state.active_project_id == project_id:
            # Choose another project if available, else None
            self.state.active_project_id = next(iter(self.state.projects.keys()), None)
        self.repo.save_debounced(self.state)


class TaskService:
    def __init__(self, state: models.AppState, repo: persistence.JsonRepository) -> None:
        self.state = state
        self.repo = repo

    def _get_project(self, project_id: str) -> models.Project:
        if project_id not in self.state.projects:
            raise KeyError("Project not found")
        return self.state.projects[project_id]

    def list_tasks(self, project_id: str) -> list[models.Task]:
        proj = self._get_project(project_id)
        return list(proj.tasks.values())

    def get_task(self, project_id: str, task_id: str) -> models.Task:
        proj = self._get_project(project_id)
        if task_id not in proj.tasks:
            raise KeyError("Task not found")
        return proj.tasks[task_id]

    def create_task(
        self,
        project_id: str,
        title: str,
        priority: str,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        due_date: Optional[str] = None,
        status: Optional[str] = None,
        dependencies: Optional[list[str]] = None,
    ) -> models.Task:
        proj = self._get_project(project_id)
        validation.validate_title(title)
        validation.validate_priority(priority)
        tags_norm = validation.normalize_tags(tags)
        due: Optional[datetime.date] = None
        if due_date:
            due = validation.parse_due_date(due_date)
        st = status if status in models.STATUSES else "To Do"
        deps = list(dependencies) if dependencies else []
        # validate deps exist and no self-dependency
        for dep_id in deps:
            if dep_id not in proj.tasks:
                raise KeyError(f"Dependency task not found: {dep_id}")
        new_task_id = str(uuid.uuid4())
        if new_task_id in deps:
            raise DependencyCycleError("Task cannot depend on itself.")
        task = models.Task(
            id=new_task_id,
            title=title.strip(),
            description=description,
            priority=priority,
            tags=tags_norm,
            due_date=due,
            status=st,
            dependencies=deps,
        )
        # If creating as Done, ensure all deps are Done
        if task.status == "Done":
            blocking = [tid for tid in task.dependencies if proj.tasks.get(tid) and proj.tasks[tid].status != "Done"]
            if blocking:
                raise BlockedCompletionError("Cannot complete: dependencies incomplete", blocking_dependencies=blocking)
        # Check for cycles with the new task inserted
        if deps:
            self._assert_no_cycle_on_set(proj, task.id, deps, preexisting_task=task, include_new=True)
        proj.add_task(task)
        self.repo.save_debounced(self.state)
        return task

    def edit_task(
        self,
        project_id: str,
        task_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[list[str]] = None,
        due_date: Optional[str] = None,
        due_date_set: bool = False,
        status: Optional[str] = None,
    ) -> models.Task:
        proj = self._get_project(project_id)
        task = self.get_task(project_id, task_id)

        if title is not None:
            validation.validate_title(title)
            task.title = title.strip()
        if description is not None:
            task.description = description
        if priority is not None:
            validation.validate_priority(priority)
            task.priority = priority
        if tags is not None:
            task.tags = validation.normalize_tags(tags)
        if due_date_set:
            if due_date:
                task.due_date = validation.parse_due_date(due_date)
            else:
                task.due_date = None
        if status is not None:
            self._set_status_with_gating(proj, task, status)

        self.repo.save_debounced(self.state)
        return task

    def set_task_status(self, project_id: str, task_id: str, new_status: str) -> models.Task:
        proj = self._get_project(project_id)
        task = self.get_task(project_id, task_id)
        self._set_status_with_gating(proj, task, new_status)
        self.repo.save_debounced(self.state)
        return task

    def move_task_between_columns(self, project_id: str, task_id: str, destination_status: str) -> models.Task:
        # Same as set status
        return self.set_task_status(project_id, task_id, destination_status)

    def delete_task(self, project_id: str, task_id: str) -> None:
        proj = self._get_project(project_id)
        if task_id not in proj.tasks:
            raise KeyError("Task not found")
        dependents = proj.find_dependents(task_id)
        if dependents:
            names = ", ".join(t.title for t in dependents)
            raise DeletionBlockedError(
                f"Cannot delete: other tasks depend on it ({names})",
                dependents=[t.id for t in dependents],
            )
        proj.remove_task(task_id)
        self.repo.save_debounced(self.state)

    def set_dependencies(self, project_id: str, task_id: str, predecessor_ids: list[str]) -> models.Task:
        proj = self._get_project(project_id)
        task = self.get_task(project_id, task_id)
        preds = list(predecessor_ids) if predecessor_ids else []
        if task_id in preds:
            raise DependencyCycleError("Task cannot depend on itself.")
        # validate existence
        for pid in preds:
            if pid not in proj.tasks:
                raise KeyError(f"Dependency task not found: {pid}")

        self._assert_no_cycle_on_set(proj, task_id, preds)
        # If task is Done, block if any preds not Done
        if task.status == "Done":
            blocking = [pid for pid in preds if proj.tasks[pid].status != "Done"]
            if blocking:
                raise BlockedCompletionError("Cannot complete: dependencies incomplete", blocking_dependencies=blocking)

        task.dependencies = preds
        self.repo.save_debounced(self.state)
        return task

    def add_tag(self, project_id: str, task_id: str, tag: str) -> models.Task:
        task = self.get_task(project_id, task_id)
        norm = validation.normalize_tags([tag])
        if not norm:
            return task
        val = norm[0]
        low = val.lower()
        if all(t.lower() != low for t in task.tags):
            task.tags.append(val)
            self.repo.save_debounced(self.state)
        return task

    def remove_tag(self, project_id: str, task_id: str, tag: str) -> models.Task:
        task = self.get_task(project_id, task_id)
        low = (tag or "").strip().lower()
        if not low:
            return task
        task.tags = [t for t in task.tags if t.lower() != low]
        self.repo.save_debounced(self.state)
        return task

    def _set_status_with_gating(self, proj: models.Project, task: models.Task, new_status: str) -> None:
        if new_status not in models.STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(models.STATUSES)}")
        if new_status == "Done":
            blocking = [tid for tid in task.dependencies if proj.tasks.get(tid) and proj.tasks[tid].status != "Done"]
            if blocking:
                raise BlockedCompletionError("Cannot complete: dependencies incomplete", blocking_dependencies=blocking)
        task.status = new_status

    def _assert_no_cycle_on_set(
        self,
        proj: models.Project,
        task_id: str,
        new_predecessors: list[str],
        *,
        preexisting_task: Optional[models.Task] = None,
        include_new: bool = False,
    ) -> None:
        # Build adjacency: task -> predecessors
        adj: dict[str, list[str]] = {}
        for tid, t in proj.tasks.items():
            adj[tid] = list(t.dependencies)
        if preexisting_task is not None and include_new:
            adj[preexisting_task.id] = list(new_predecessors)
        else:
            adj[task_id] = list(new_predecessors)

        # Check for path from any new predecessor to task_id
        target = task_id

        def dfs(start: str, visited: set[str]) -> bool:
            if start == target:
                return True
            visited.add(start)
            for n in adj.get(start, []):
                if n in visited:
                    continue
                if dfs(n, visited):
                    return True
            return False

        for pred in new_predecessors:
            if dfs(pred, set()):
                raise DependencyCycleError("Circular dependency detected.")
