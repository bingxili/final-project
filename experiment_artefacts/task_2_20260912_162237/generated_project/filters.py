from __future__ import annotations

from typing import Optional, Set

import models
from validation import parse_due_date


def filter_tasks(
    tasks: list[models.Task],
    status: Optional[set[str]] = None,
    priorities: Optional[set[str]] = None,
    tags_any_of: Optional[set[str]] = None,
    due_date_start: Optional[str] = None,
    due_date_end: Optional[str] = None,
) -> list[models.Task]:
    status_set = set(status) if status else None
    prio_set = set(priorities) if priorities else None
    tags_set = {t.lower() for t in tags_any_of} if tags_any_of else None

    start_date = parse_due_date(due_date_start) if due_date_start else None
    end_date = parse_due_date(due_date_end) if due_date_end else None

    def include(task: models.Task) -> bool:
        if status_set is not None and task.status not in status_set:
            return False
        if prio_set is not None and task.priority not in prio_set:
            return False
        if tags_set is not None:
            task_tags_low = {t.lower() for t in task.tags}
            if task_tags_low.isdisjoint(tags_set):
                return False
        if start_date or end_date:
            if task.due_date is None:
                return False
            if start_date and task.due_date < start_date:
                return False
            if end_date and task.due_date > end_date:
                return False
        return True

    return [t for t in tasks if include(t)]
