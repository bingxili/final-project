from __future__ import annotations

import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field
import uuid

STATUSES = ("To Do", "In Progress", "Done")
PRIORITIES = ("Low", "Medium", "High")


class Task:
    def __init__(
        self,
        id: str,
        title: str,
        priority: str,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        due_date: Optional[datetime.date] = None,
        status: str = "To Do",
        dependencies: Optional[list[str]] = None,
    ) -> None:
        self.id: str = id
        self.title: str = title
        self.description: Optional[str] = description
        self.priority: str = priority
        self.tags: list[str] = list(tags) if tags else []
        self.due_date: Optional[datetime.date] = due_date
        self.status: str = status
        self.dependencies: list[str] = list(dependencies) if dependencies else []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "tags": list(self.tags),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status,
            "dependencies": list(self.dependencies),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        due = data.get("due_date")
        due_date = datetime.date.fromisoformat(due) if due else None
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description"),
            priority=data["priority"],
            tags=data.get("tags") or [],
            due_date=due_date,
            status=data.get("status", "To Do"),
            dependencies=data.get("dependencies") or [],
        )


class Project:
    def __init__(self, id: str, name: str, tasks: Optional[dict[str, Task]] = None) -> None:
        self.id: str = id
        self.name: str = name
        self.tasks: dict[str, Task] = dict(tasks) if tasks else {}

    def add_task(self, task: Task) -> None:
        self.tasks[task.id] = task

    def remove_task(self, task_id: str) -> None:
        if task_id in self.tasks:
            del self.tasks[task_id]

    def find_dependents(self, task_id: str) -> list[Task]:
        dependents: list[Task] = []
        for t in self.tasks.values():
            if task_id in t.dependencies:
                dependents.append(t)
        return dependents

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tasks": {tid: t.to_dict() for tid, t in self.tasks.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        tasks_dict = {tid: Task.from_dict(tdata) for tid, tdata in (data.get("tasks") or {}).items()}
        return cls(id=data["id"], name=data["name"], tasks=tasks_dict)


class AppState:
    def __init__(self, projects: Optional[dict[str, Project]] = None, active_project_id: Optional[str] = None) -> None:
        self.projects: dict[str, Project] = dict(projects) if projects else {}
        self.active_project_id: Optional[str] = active_project_id

    def get_active_project(self) -> Optional[Project]:
        if self.active_project_id and self.active_project_id in self.projects:
            return self.projects[self.active_project_id]
        return None

    def set_active_project(self, project_id: Optional[str]) -> None:
        self.active_project_id = project_id

    def to_dict(self) -> dict:
        return {
            "projects": {pid: proj.to_dict() for pid, proj in self.projects.items()},
            "active_project_id": self.active_project_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppState":
        projects = {pid: Project.from_dict(pdata) for pid, pdata in (data.get("projects") or {}).items()}
        active = data.get("active_project_id")
        return cls(projects=projects, active_project_id=active)
