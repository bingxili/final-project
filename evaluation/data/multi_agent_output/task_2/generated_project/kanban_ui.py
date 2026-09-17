from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Optional, Set

import models
import services
from filters import filter_tasks
from stats import compute_statistics
from validation import validate_title, validate_priority, parse_due_date, normalize_tags


class KanbanUI:
    def __init__(self, root: tk.Tk, project_service: services.ProjectService, task_service: services.TaskService) -> None:
        self.root = root
        self.project_service = project_service
        self.task_service = task_service

        self.main_frame: Optional[tk.Frame] = None
        self.projects_listbox: Optional[tk.Listbox] = None
        self.columns: dict[str, tk.Listbox] = {}
        self.status_filters_vars: dict[str, tk.BooleanVar] = {}
        self.priority_vars: dict[str, tk.BooleanVar] = {}
        self.tags_entry: Optional[ttk.Entry] = None
        self.due_start_entry: Optional[ttk.Entry] = None
        self.due_end_entry: Optional[ttk.Entry] = None
        self.stats_var: Optional[tk.StringVar] = None

        self._current_filters = {}

    def build(self) -> tk.Frame:
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill="both", expand=True)

        self.root.title("Kanban Manager")

        # Left sidebar for projects
        sidebar = ttk.Frame(self.main_frame)
        sidebar.pack(side="left", fill="y", padx=5, pady=5)

        ttk.Label(sidebar, text="Projects").pack(anchor="w")

        self.projects_listbox = tk.Listbox(sidebar, height=10, exportselection=False)
        self.projects_listbox.pack(fill="y")
        self.projects_listbox.bind("<<ListboxSelect>>", lambda e: self._on_project_selected())

        btn_frame = ttk.Frame(sidebar)
        btn_frame.pack(fill="x", pady=5)
        ttk.Button(btn_frame, text="Add", command=self._on_add_project).pack(side="left", expand=True, fill="x")
        ttk.Button(btn_frame, text="Rename", command=self._on_rename_project).pack(side="left", expand=True, fill="x")
        ttk.Button(btn_frame, text="Delete", command=self._on_delete_project).pack(side="left", expand=True, fill="x")

        # Filters
        filters_frame = ttk.LabelFrame(sidebar, text="Filters")
        filters_frame.pack(fill="x", pady=5)

        # Status filters
        status_frame = ttk.Frame(filters_frame)
        status_frame.pack(fill="x")
        ttk.Label(status_frame, text="Status").pack(anchor="w")
        for st in models.STATUSES:
            var = tk.BooleanVar(value=False)
            self.status_filters_vars[st] = var
            ttk.Checkbutton(status_frame, text=st, variable=var, command=self._on_apply_filters).pack(anchor="w")

        # Priority filters
        prio_frame = ttk.Frame(filters_frame)
        prio_frame.pack(fill="x", pady=(5, 0))
        ttk.Label(prio_frame, text="Priority").pack(anchor="w")
        for p in ("Low", "Medium", "High"):
            var = tk.BooleanVar(value=False)
            self.priority_vars[p] = var
            ttk.Checkbutton(prio_frame, text=p, variable=var, command=self._on_apply_filters).pack(anchor="w")

        # Tags any-of
        tags_frame = ttk.Frame(filters_frame)
        tags_frame.pack(fill="x", pady=(5, 0))
        ttk.Label(tags_frame, text="Tags (comma, any-of)").pack(anchor="w")
        self.tags_entry = ttk.Entry(tags_frame)
        self.tags_entry.pack(fill="x")

        # Due date range
        due_frame = ttk.Frame(filters_frame)
        due_frame.pack(fill="x", pady=(5, 0))
        ttk.Label(due_frame, text="Due start (YYYY-MM-DD)").pack(anchor="w")
        self.due_start_entry = ttk.Entry(due_frame)
        self.due_start_entry.pack(fill="x")
        ttk.Label(due_frame, text="Due end (YYYY-MM-DD)").pack(anchor="w")
        self.due_end_entry = ttk.Entry(due_frame)
        self.due_end_entry.pack(fill="x")

        act_frame = ttk.Frame(filters_frame)
        act_frame.pack(fill="x", pady=5)
        ttk.Button(act_frame, text="Apply", command=self._on_apply_filters).pack(side="left", expand=True, fill="x")
        ttk.Button(act_frame, text="Clear", command=self.clear_filters).pack(side="left", expand=True, fill="x")

        # Main area: board
        board = ttk.Frame(self.main_frame)
        board.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        header = ttk.Frame(board)
        header.pack(fill="x")
        ttk.Button(header, text="Add Task", command=self._on_add_task).pack(side="left")
        ttk.Button(header, text="Edit Task", command=self._on_edit_task).pack(side="left")
        ttk.Button(header, text="Delete Task", command=self._on_delete_task).pack(side="left")
        ttk.Button(header, text="Set Dependencies", command=self._on_set_dependencies).pack(side="left")
        ttk.Button(header, text="Move To Do", command=lambda: self._on_move_task("To Do")).pack(side="left")
        ttk.Button(header, text="Move In Progress", command=lambda: self._on_move_task("In Progress")).pack(side="left")
        ttk.Button(header, text="Move Done", command=lambda: self._on_move_task("Done")).pack(side="left")

        self.stats_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.stats_var).pack(side="right")

        cols_frame = ttk.Frame(board)
        cols_frame.pack(fill="both", expand=True)

        for st in models.STATUSES:
            col = ttk.Frame(cols_frame, relief="groove", borderwidth=2)
            col.pack(side="left", fill="both", expand=True, padx=5)
            ttk.Label(col, text=st, font=("", 10, "bold")).pack()
            lb = tk.Listbox(col, exportselection=False)
            lb.pack(fill="both", expand=True)
            lb.bind("<Double-1>", lambda e, s=st: self._on_column_double_click(s))
            self.columns[st] = lb

        self.refresh()
        return self.main_frame

    def refresh(self) -> None:
        # Refresh projects list
        if self.projects_listbox is not None:
            self.projects_listbox.delete(0, tk.END)
            projects = self.project_service.list_projects()
            for p in projects:
                self.projects_listbox.insert(tk.END, f"{p.name} ({p.id[:6]})")
            # Select active
            active = self.project_service.state.active_project_id
            if active:
                # find index
                for idx, p in enumerate(projects):
                    if p.id == active:
                        self.projects_listbox.select_set(idx)
                        self.projects_listbox.see(idx)
                        break

        # Refresh tasks in columns
        active_project = self.project_service.state.get_active_project()
        for st, lb in self.columns.items():
            lb.delete(0, tk.END)
        if active_project is None:
            self._update_stats(None)
            return

        tasks = list(active_project.tasks.values())
        filt = self._current_filters
        if filt:
            tasks = filter_tasks(
                tasks,
                status=filt.get("status"),
                priorities=filt.get("priorities"),
                tags_any_of=filt.get("tags_any_of"),
                due_date_start=filt.get("due_date_start"),
                due_date_end=filt.get("due_date_end"),
            )
        # Group by status
        groups = {st: [] for st in models.STATUSES}
        for t in tasks:
            groups.setdefault(t.status, []).append(t)
        for st in models.STATUSES:
            for t in sorted(groups.get(st, []), key=lambda x: x.title.lower()):
                tags_repr = f" [{', '.join(t.tags)}]" if t.tags else ""
                due = f" (due {t.due_date.isoformat()})" if t.due_date else ""
                self.columns[st].insert(tk.END, f"{t.title}{tags_repr}{due} | {t.priority} | {t.id[:6]}")

        self._update_stats(active_project)

    def apply_filters(
        self,
        status: Optional[set[str]] = None,
        priorities: Optional[set[str]] = None,
        tags_any_of: Optional[set[str]] = None,
        due_date_start: Optional[str] = None,
        due_date_end: Optional[str] = None,
    ) -> None:
        self._current_filters = {
            "status": status,
            "priorities": priorities,
            "tags_any_of": tags_any_of,
            "due_date_start": due_date_start,
            "due_date_end": due_date_end,
        }
        self.refresh()

    def clear_filters(self) -> None:
        if self.tags_entry:
            self.tags_entry.delete(0, tk.END)
        if self.due_start_entry:
            self.due_start_entry.delete(0, tk.END)
        if self.due_end_entry:
            self.due_end_entry.delete(0, tk.END)
        for var in self.status_filters_vars.values():
            var.set(False)
        for var in self.priority_vars.values():
            var.set(False)
        self._current_filters = {}
        self.refresh()

    # Internal UI helpers

    def _on_project_selected(self) -> None:
        if self.projects_listbox is None:
            return
        sel = self.projects_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        projects = self.project_service.list_projects()
        if idx >= len(projects):
            return
        proj = projects[idx]
        self.project_service.set_active_project(proj.id)
        self.refresh()

    def _on_add_project(self) -> None:
        name = simpledialog.askstring("New Project", "Project name:")
        if not name:
            return
        try:
            self.project_service.create_project(name)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.refresh()

    def _on_rename_project(self) -> None:
        active = self.project_service.state.get_active_project()
        if not active:
            messagebox.showinfo("Info", "No active project.")
            return
        name = simpledialog.askstring("Rename Project", "New name:", initialvalue=active.name)
        if not name:
            return
        try:
            self.project_service.rename_project(active.id, name)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.refresh()

    def _on_delete_project(self) -> None:
        active = self.project_service.state.get_active_project()
        if not active:
            messagebox.showinfo("Info", "No active project.")
            return
        if not messagebox.askyesno("Confirm", f"Delete project '{active.name}' and all its tasks?"):
            return
        try:
            self.project_service.delete_project(active.id)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.refresh()

    def _get_selected_task_id_and_status(self) -> Optional[tuple[str, str]]:
        # Search selection in each column
        for st, lb in self.columns.items():
            sel = lb.curselection()
            if sel:
                idx = sel[0]
                # Extract id from string ... | idprefix
                text = lb.get(idx)
                if "|" in text:
                    suffix = text.split("|")[-1].strip()
                    id_prefix = suffix
                    # find task by prefix
                    proj = self.project_service.state.get_active_project()
                    if not proj:
                        return None
                    for tid, t in proj.tasks.items():
                        if tid.startswith(id_prefix):
                            return tid, st
                # fallback: cannot determine
        return None

    def _on_add_task(self) -> None:
        proj = self.project_service.state.get_active_project()
        if not proj:
            messagebox.showinfo("Info", "Create or select a project first.")
            return
        dlg = TaskDialog(self.root, title="Add Task")
        res = dlg.result
        if not res:
            return
        try:
            self.task_service.create_task(
                proj.id,
                title=res["title"],
                priority=res["priority"],
                description=res.get("description"),
                tags=res.get("tags"),
                due_date=res.get("due_date"),
                status=res.get("status"),
                dependencies=[],
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.refresh()

    def _on_edit_task(self) -> None:
        proj = self.project_service.state.get_active_project()
        if not proj:
            return
        sel = self._get_selected_task_id_and_status()
        if not sel:
            messagebox.showinfo("Info", "Select a task to edit.")
            return
        tid, _ = sel
        task = proj.tasks[tid]
        dlg = TaskDialog(
            self.root,
            title="Edit Task",
            initial={
                "title": task.title,
                "description": task.description or "",
                "priority": task.priority,
                "tags": ", ".join(task.tags),
                "due_date": task.due_date.isoformat() if task.due_date else "",
                "status": task.status,
            },
        )
        res = dlg.result
        if not res:
            return
        try:
            self.task_service.edit_task(
                proj.id,
                tid,
                title=res["title"],
                description=res.get("description"),
                priority=res.get("priority"),
                tags=res.get("tags"),
                due_date=res.get("due_date"),
                due_date_set=True,
                status=res.get("status"),
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.refresh()

    def _on_delete_task(self) -> None:
        proj = self.project_service.state.get_active_project()
        if not proj:
            return
        sel = self._get_selected_task_id_and_status()
        if not sel:
            messagebox.showinfo("Info", "Select a task to delete.")
            return
        tid, _ = sel
        task = proj.tasks[tid]
        if not messagebox.askyesno("Confirm", f"Delete task '{task.title}'?"):
            return
        try:
            self.task_service.delete_task(proj.id, tid)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.refresh()

    def _on_move_task(self, dest_status: str) -> None:
        proj = self.project_service.state.get_active_project()
        if not proj:
            return
        sel = self._get_selected_task_id_and_status()
        if not sel:
            messagebox.showinfo("Info", "Select a task to move.")
            return
        tid, _ = sel
        try:
            self.task_service.move_task_between_columns(proj.id, tid, dest_status)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.refresh()

    def _on_set_dependencies(self) -> None:
        proj = self.project_service.state.get_active_project()
        if not proj:
            return
        sel = self._get_selected_task_id_and_status()
        if not sel:
            messagebox.showinfo("Info", "Select a task to set dependencies.")
            return
        tid, _ = sel
        task = proj.tasks[tid]
        dlg = DependenciesDialog(self.root, proj, task)
        if dlg.result is None:
            return
        try:
            self.task_service.set_dependencies(proj.id, task.id, dlg.result)
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.refresh()

    def _on_column_double_click(self, status: str) -> None:
        # Show details of selected task in that column
        proj = self.project_service.state.get_active_project()
        if not proj:
            return
        lb = self.columns.get(status)
        if not lb:
            return
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        text = lb.get(idx)
        # parse id prefix suffix after |
        if "|" in text:
            id_prefix = text.split("|")[-1].strip()
            for tid, t in proj.tasks.items():
                if tid.startswith(id_prefix):
                    self._show_task_details(t, proj)
                    break

    def _show_task_details(self, task: models.Task, proj: models.Project) -> None:
        top = tk.Toplevel(self.root)
        top.title("Task Details")
        txt = tk.Text(top, width=60, height=20)
        txt.pack(fill="both", expand=True)
        deps = [proj.tasks[dep].title if dep in proj.tasks else dep for dep in task.dependencies]
        lines = [
            f"Title: {task.title}",
            f"Description: {task.description or ''}",
            f"Priority: {task.priority}",
            f"Tags: {', '.join(task.tags)}",
            f"Due Date: {task.due_date.isoformat() if task.due_date else ''}",
            f"Status: {task.status}",
            f"Dependencies: {', '.join(deps)}",
            f"ID: {task.id}",
        ]
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")

    def _on_apply_filters(self) -> None:
        status = {k for k, var in self.status_filters_vars.items() if var.get()}
        priorities = {k for k, var in self.priority_vars.items() if var.get()}
        tags_text = self.tags_entry.get().strip() if self.tags_entry else ""
        tags_set = {t.strip() for t in tags_text.split(",")} if tags_text else set()
        if "" in tags_set:
            tags_set.remove("")
        due_start = self.due_start_entry.get().strip() if self.due_start_entry else ""
        due_end = self.due_end_entry.get().strip() if self.due_end_entry else ""
        # Validate date format if provided
        try:
            if due_start:
                parse_due_date(due_start)
            if due_end:
                parse_due_date(due_end)
        except Exception as e:
            messagebox.showerror("Invalid date", str(e))
            return
        self.apply_filters(
            status=status if status else None,
            priorities=priorities if priorities else None,
            tags_any_of=tags_set if tags_set else None,
            due_date_start=due_start or None,
            due_date_end=due_end or None,
        )

    def _update_stats(self, project: Optional[models.Project]) -> None:
        if self.stats_var is None:
            return
        if not project:
            self.stats_var.set("")
            return
        stats = compute_statistics(project)
        self.stats_var.set(
            f"To Do: {stats['todo_count']} | In Progress: {stats['in_progress_count']} | "
            f"Done: {stats['done_count']} | Overdue: {stats['overdue_count']} | "
            f"Completion: {stats['completion_percent']}%"
        )


class TaskDialog:
    def __init__(self, parent: tk.Tk, title: str, initial: Optional[dict] = None) -> None:
        self.result: Optional[dict] = None
        top = self.top = tk.Toplevel(parent)
        top.title(title)
        top.grab_set()

        init = initial or {}

        ttk.Label(top, text="Title").grid(row=0, column=0, sticky="w")
        self.title_entry = ttk.Entry(top)
        self.title_entry.grid(row=0, column=1, sticky="ew")
        self.title_entry.insert(0, init.get("title", ""))

        ttk.Label(top, text="Description").grid(row=1, column=0, sticky="w")
        self.desc_entry = ttk.Entry(top)
        self.desc_entry.grid(row=1, column=1, sticky="ew")
        self.desc_entry.insert(0, init.get("description", ""))

        ttk.Label(top, text="Priority").grid(row=2, column=0, sticky="w")
        self.prio_cb = ttk.Combobox(top, values=["Low", "Medium", "High"], state="readonly")
        self.prio_cb.grid(row=2, column=1, sticky="ew")
        self.prio_cb.set(init.get("priority", "Medium"))

        ttk.Label(top, text="Tags (comma-separated)").grid(row=3, column=0, sticky="w")
        self.tags_entry = ttk.Entry(top)
        self.tags_entry.grid(row=3, column=1, sticky="ew")
        self.tags_entry.insert(0, init.get("tags", ""))

        ttk.Label(top, text="Due Date (YYYY-MM-DD)").grid(row=4, column=0, sticky="w")
        self.due_entry = ttk.Entry(top)
        self.due_entry.grid(row=4, column=1, sticky="ew")
        self.due_entry.insert(0, init.get("due_date", ""))

        ttk.Label(top, text="Status").grid(row=5, column=0, sticky="w")
        self.status_cb = ttk.Combobox(top, values=list(models.STATUSES), state="readonly")
        self.status_cb.grid(row=5, column=1, sticky="ew")
        self.status_cb.set(init.get("status", "To Do"))

        btn_frame = ttk.Frame(top)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=5)
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side="left")
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side="left")

        top.columnconfigure(1, weight=1)
        self.title_entry.focus_set()
        parent.wait_window(top)

    def _on_ok(self) -> None:
        title = self.title_entry.get()
        try:
            validate_title(title)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        prio = self.prio_cb.get()
        try:
            validate_priority(prio)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        due_text = self.due_entry.get().strip()
        if due_text:
            try:
                parse_due_date(due_text)
            except Exception as e:
                messagebox.showerror("Error", str(e))
                return
        tags_text = self.tags_entry.get().strip()
        tags = [s.strip() for s in tags_text.split(",")] if tags_text else []
        tags = normalize_tags(tags)
        self.result = {
            "title": title.strip(),
            "description": self.desc_entry.get(),
            "priority": prio,
            "tags": tags,
            "due_date": due_text or None,
            "status": self.status_cb.get() or "To Do",
        }
        self.top.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.top.destroy()


class DependenciesDialog:
    def __init__(self, parent: tk.Tk, project: models.Project, task: models.Task) -> None:
        self.result: Optional[list[str]] = None
        top = self.top = tk.Toplevel(parent)
        top.title("Set Dependencies")
        top.grab_set()

        ttk.Label(top, text=f"Select predecessors for '{task.title}'").pack(anchor="w")
        self.listbox = tk.Listbox(top, selectmode="multiple")
        self.listbox.pack(fill="both", expand=True)

        self._ids: list[str] = []
        for tid, t in project.tasks.items():
            if tid == task.id:
                continue
            self.listbox.insert(tk.END, f"{t.title} ({t.status}) [{tid[:6]}]")
            self._ids.append(tid)
            if tid in task.dependencies:
                self.listbox.selection_set(len(self._ids) - 1)

        btn_frame = ttk.Frame(top)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side="left")
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side="left")

        parent.wait_window(top)

    def _on_ok(self) -> None:
        sel = self.listbox.curselection()
        self.result = [self._ids[i] for i in sel]
        self.top.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.top.destroy()
