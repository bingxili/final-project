from __future__ import annotations

import datetime
from typing import Optional

import models


def compute_statistics(project: models.Project, today: Optional[datetime.date] = None) -> dict[str, int | float]:
    tasks = list(project.tasks.values())
    todo = sum(1 for t in tasks if t.status == "To Do")
    inprog = sum(1 for t in tasks if t.status == "In Progress")
    done = sum(1 for t in tasks if t.status == "Done")
    if today is None:
        today = datetime.date.today()
    overdue = sum(1 for t in tasks if t.status != "Done" and t.due_date is not None and t.due_date < today)
    total = len(tasks)
    completion = round((done / total) * 100) if total > 0 else 0
    return {
        "todo_count": todo,
        "in_progress_count": inprog,
        "done_count": done,
        "overdue_count": overdue,
        "completion_percent": int(completion),
    }
