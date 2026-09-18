import tkinter as tk

import persistence
import services
import models
from kanban_ui import KanbanUI


def main() -> None:
    repo = persistence.JsonRepository()
    state = repo.load()
    proj_service = services.ProjectService(state, repo)
    task_service = services.TaskService(state, repo)

    root = tk.Tk()
    ui = KanbanUI(root, proj_service, task_service)
    ui.build()
    root.mainloop()


if __name__ == "__main__":
    main()