import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import uuid
from datetime import datetime, date
from typing import List, Dict, Any, Optional

DATA_FILE = "kanban_data.json"
STATUSES = ["To Do", "In Progress", "Done"]
PRIORITIES = ["Low", "Medium", "High"]
DATE_FMT = "%Y-%m-%d"


def today_str():
    return date.today().strftime(DATE_FMT)


def safe_parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, DATE_FMT).date()
    except Exception:
        return None


def format_task_line(t: Dict[str, Any]) -> str:
    pr = t.get("priority", "Medium")
    pr_symbol = {"High": "[H]", "Medium": "[M]", "Low": "[L]"}.get(pr, "[M]")
    due = t.get("due_date") or ""
    tags = t.get("tags", [])
    tags_str = " ".join(f"#{x}" for x in tags)
    dep_count = len(t.get("dependencies", []))
    dep_str = f" ⛓{dep_count}" if dep_count else ""
    title = t.get("title", "")
    return f"{pr_symbol} {title}  (Due: {due})  {tags_str}{dep_str}"


def ensure_data_shape(data: Dict[str, Any]) -> Dict[str, Any]:
    data = data or {}
    projects = data.get("projects")
    if not isinstance(projects, list):
        projects = []
    for p in projects:
        p.setdefault("id", str(uuid.uuid4()))
        p.setdefault("name", "Untitled Project")
        tasks = p.get("tasks")
        if not isinstance(tasks, list):
            tasks = []
        for t in tasks:
            t.setdefault("id", str(uuid.uuid4()))
            t.setdefault("title", "Untitled")
            t.setdefault("description", "")
            t.setdefault("priority", "Medium")
            t.setdefault("tags", [])
            t.setdefault("due_date", "")
            t.setdefault("status", "To Do")
            t.setdefault("dependencies", [])
        p["tasks"] = tasks
    data["projects"] = projects
    data.setdefault("selected_project_id", projects[0]["id"] if projects else None)
    return data


class TaskDialog(tk.Toplevel):
    def __init__(self, master, project: Dict[str, Any], task: Optional[Dict[str, Any]] = None):
        super().__init__(master)
        self.title("Task Editor")
        self.resizable(True, True)
        self.project = project
        self.task = task
        self.result: Optional[Dict[str, Any]] = None
        self.geometry("600x600")

        self.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(self, text="Title:").grid(row=row, column=0, sticky="w", padx=6, pady=4)
        self.title_var = tk.StringVar(value=(task.get("title") if task else ""))
        self.title_entry = ttk.Entry(self, textvariable=self.title_var)
        self.title_entry.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        row += 1

        ttk.Label(self, text="Description:").grid(row=row, column=0, sticky="nw", padx=6, pady=4)
        self.desc_text = tk.Text(self, height=6)
        self.desc_text.grid(row=row, column=1, sticky="nsew", padx=6, pady=4)
        if task:
            self.desc_text.insert("1.0", task.get("description", ""))
        row += 1

        ttk.Label(self, text="Priority:").grid(row=row, column=0, sticky="w", padx=6, pady=4)
        self.priority_var = tk.StringVar(value=(task.get("priority") if task else "Medium"))
        self.priority_cb = ttk.Combobox(self, textvariable=self.priority_var, values=PRIORITIES, state="readonly")
        self.priority_cb.grid(row=row, column=1, sticky="w", padx=6, pady=4)
        row += 1

        ttk.Label(self, text="Tags (comma-separated):").grid(row=row, column=0, sticky="w", padx=6, pady=4)
        self.tags_var = tk.StringVar(value=(",".join(task.get("tags", [])) if task else ""))
        self.tags_entry = ttk.Entry(self, textvariable=self.tags_var)
        self.tags_entry.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        row += 1

        ttk.Label(self, text="Due Date (YYYY-MM-DD):").grid(row=row, column=0, sticky="w", padx=6, pady=4)
        self.due_var = tk.StringVar(value=(task.get("due_date") if task else ""))
        self.due_entry = ttk.Entry(self, textvariable=self.due_var)
        self.due_entry.grid(row=row, column=1, sticky="w", padx=6, pady=4)
        row += 1

        ttk.Label(self, text="Status:").grid(row=row, column=0, sticky="w", padx=6, pady=4)
        self.status_var = tk.StringVar(value=(task.get("status") if task else "To Do"))
        self.status_cb = ttk.Combobox(self, textvariable=self.status_var, values=STATUSES, state="readonly")
        self.status_cb.grid(row=row, column=1, sticky="w", padx=6, pady=4)
        row += 1

        # Dependencies
        ttk.Label(self, text="Dependencies (select tasks that must be completed first):").grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=(10, 4))
        row += 1

        dep_frame = ttk.Frame(self)
        dep_frame.grid(row=row, column=0, columnspan=2, sticky="nsew", padx=6, pady=4)
        self.rowconfigure(row, weight=1)

        dep_frame.rowconfigure(0, weight=1)
        dep_frame.columnconfigure(0, weight=1)

        self.dep_list = tk.Listbox(dep_frame, selectmode=tk.MULTIPLE)
        dep_scroll = ttk.Scrollbar(dep_frame, orient="vertical", command=self.dep_list.yview)
        self.dep_list.configure(yscrollcommand=dep_scroll.set)
        self.dep_list.grid(row=0, column=0, sticky="nsew")
        dep_scroll.grid(row=0, column=1, sticky="ns")

        self.task_index_to_id: List[str] = []
        current_deps = set(task.get("dependencies", []) if task else [])
        for other in self.project.get("tasks", []):
            if task and other.get("id") == task.get("id"):
                continue
            self.task_index_to_id.append(other["id"])
            display = f"{other.get('title','')}  ({other['status']})"
            self.dep_list.insert(tk.END, display)
            if other["id"] in current_deps:
                self.dep_list.selection_set(tk.END)

        row += 1

        # Buttons
        btns = ttk.Frame(self)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", padx=6, pady=10)
        save_btn = ttk.Button(btns, text="Save", command=self.on_save)
        cancel_btn = ttk.Button(btns, text="Cancel", command=self.destroy)
        save_btn.grid(row=0, column=0, padx=4)
        cancel_btn.grid(row=0, column=1, padx=4)

        self.bind("<Return>", lambda e: self.on_save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.title_entry.focus_set()

    def on_save(self):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showerror("Validation", "Title is required.")
            return
        due_s = self.due_var.get().strip()
        if due_s and not safe_parse_date(due_s):
            messagebox.showerror("Validation", "Due date must be YYYY-MM-DD.")
            return
        tags = [x.strip() for x in self.tags_var.get().split(",") if x.strip()]
        status = self.status_var.get()
        pr = self.priority_var.get()

        sel_indices = self.dep_list.curselection()
        dep_ids = [self.task_index_to_id[i] for i in sel_indices]

        self.result = {
            "title": title,
            "description": self.desc_text.get("1.0", "end").strip(),
            "priority": pr,
            "tags": tags,
            "due_date": due_s,
            "status": status,
            "dependencies": dep_ids,
        }
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Local Project Management - Kanban")
        self.geometry("1200x750")

        self.data: Dict[str, Any] = ensure_data_shape(self.load_data())

        self.create_ui()
        self.refresh_projects_list()
        self.restore_selection()
        self.apply_filters_and_render()

    def load_data(self) -> Dict[str, Any]:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                messagebox.showwarning("Load Error", "Failed to read data file. Starting with empty workspace.")
        return {"projects": []}

    def save_data(self):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save data: {e}")

    # UI Construction
    def create_ui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        # Left: Projects panel
        left = ttk.Frame(self)
        left.grid(row=0, column=0, rowspan=3, sticky="nsw")
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Projects", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        self.projects_list = tk.Listbox(left, height=10)
        self.projects_list.grid(row=1, column=0, sticky="nsw", padx=8)
        self.projects_list.bind("<<ListboxSelect>>", lambda e: self.on_project_select())

        proj_btns = ttk.Frame(left)
        proj_btns.grid(row=2, column=0, sticky="w", padx=8, pady=8)
        ttk.Button(proj_btns, text="Add", command=self.add_project).grid(row=0, column=0, padx=2)
        ttk.Button(proj_btns, text="Rename", command=self.rename_project).grid(row=0, column=1, padx=2)
        ttk.Button(proj_btns, text="Delete", command=self.delete_project).grid(row=0, column=2, padx=2)

        # Top: Filters
        top = ttk.Frame(self)
        top.grid(row=0, column=1, sticky="ew")
        for i in range(10):
            top.columnconfigure(i, weight=1)

        ttk.Label(top, text="Search:").grid(row=0, column=0, sticky="e", padx=4, pady=6)
        self.search_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.search_var).grid(row=0, column=1, sticky="ew", padx=4)

        ttk.Label(top, text="Status:").grid(row=0, column=2, sticky="e")
        self.status_filter = tk.StringVar(value="All")
        ttk.Combobox(top, textvariable=self.status_filter, values=["All"] + STATUSES, width=12, state="readonly").grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(top, text="Priority:").grid(row=0, column=4, sticky="e")
        self.priority_filter = tk.StringVar(value="All")
        ttk.Combobox(top, textvariable=self.priority_filter, values=["All"] + PRIORITIES, width=10, state="readonly").grid(row=0, column=5, sticky="w", padx=4)

        ttk.Label(top, text="Tags (comma):").grid(row=0, column=6, sticky="e")
        self.tags_filter = tk.StringVar()
        ttk.Entry(top, textvariable=self.tags_filter).grid(row=0, column=7, sticky="ew", padx=4)

        ttk.Label(top, text="Due From:").grid(row=0, column=8, sticky="e")
        self.due_from_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.due_from_var, width=12).grid(row=0, column=9, sticky="w", padx=4)

        ttk.Label(top, text="Due To:").grid(row=0, column=10, sticky="e")
        self.due_to_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.due_to_var, width=12).grid(row=0, column=11, sticky="w", padx=4)

        ttk.Button(top, text="Apply Filters", command=self.apply_filters_and_render).grid(row=0, column=12, padx=4)
        ttk.Button(top, text="Clear", command=self.clear_filters).grid(row=0, column=13, padx=4)

        # Center: Kanban Board
        board = ttk.Frame(self)
        board.grid(row=1, column=1, sticky="nsew")
        for i in range(3):
            board.columnconfigure(i, weight=1)
        board.rowconfigure(1, weight=1)

        # Column headers and listboxes
        self.columns = {}
        for idx, status in enumerate(STATUSES):
            col_frame = ttk.Frame(board, padding=6)
            col_frame.grid(row=0, column=idx, rowspan=2, sticky="nsew")
            col_frame.rowconfigure(1, weight=1)

            header = ttk.Frame(col_frame)
            header.grid(row=0, column=0, sticky="ew")
            header.columnconfigure(0, weight=1)
            ttk.Label(header, text=status, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
            ttk.Button(header, text="+", width=3, command=lambda s=status: self.add_task(s)).grid(row=0, column=1, sticky="e")

            listbox = tk.Listbox(col_frame)
            listbox.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
            scrollbar = ttk.Scrollbar(col_frame, orient="vertical", command=listbox.yview)
            listbox.configure(yscrollcommand=scrollbar.set)
            scrollbar.grid(row=1, column=1, sticky="ns")

            listbox.bind("<Double-Button-1>", lambda e, s=status: self.on_edit_selected(s))
            listbox.bind("<Button-3>", lambda e, s=status: self.on_context_menu(e, s))
            listbox.bind("<Button-2>", lambda e, s=status: self.on_context_menu(e, s))  # middle click for some OS

            self.columns[status] = {
                "frame": col_frame,
                "listbox": listbox,
                "index_to_task_id": [],
            }

        # Bottom: Stats
        bottom = ttk.Frame(self)
        bottom.grid(row=2, column=1, sticky="ew", pady=6)
        for i in range(10):
            bottom.columnconfigure(i, weight=1)

        self.stat_todo = tk.StringVar(value="To Do: 0")
        self.stat_prog = tk.StringVar(value="In Progress: 0")
        self.stat_done = tk.StringVar(value="Done: 0")
        self.stat_overdue = tk.StringVar(value="Overdue: 0")
        self.stat_completion = tk.StringVar(value="Completion: 0%")

        ttk.Label(bottom, textvariable=self.stat_todo).grid(row=0, column=0, sticky="w", padx=8)
        ttk.Label(bottom, textvariable=self.stat_prog).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(bottom, textvariable=self.stat_done).grid(row=0, column=2, sticky="w", padx=8)
        ttk.Label(bottom, textvariable=self.stat_overdue, foreground="#b00020").grid(row=0, column=3, sticky="w", padx=8)
        ttk.Label(bottom, textvariable=self.stat_completion).grid(row=0, column=4, sticky="w", padx=8)

        # Context menu
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Edit", command=self.menu_edit)
        self.menu.add_command(label="Delete", command=self.menu_delete)
        self.menu.add_separator()
        self.menu.add_command(label="Move to To Do", command=lambda: self.menu_move("To Do"))
        self.menu.add_command(label="Move to In Progress", command=lambda: self.menu_move("In Progress"))
        self.menu.add_command(label="Move to Done", command=lambda: self.menu_move("Done"))

        self.menu_context = {"status": None, "index": None}

    # Project management
    def refresh_projects_list(self):
        self.projects_list.delete(0, tk.END)
        for p in self.data.get("projects", []):
            self.projects_list.insert(tk.END, p.get("name", "Untitled"))

    def restore_selection(self):
        sel_id = self.data.get("selected_project_id")
        idx = 0
        for i, p in enumerate(self.data.get("projects", [])):
            if p["id"] == sel_id:
                idx = i
                break
        if self.data.get("projects"):
            self.projects_list.selection_clear(0, tk.END)
            self.projects_list.selection_set(idx)
            self.projects_list.see(idx)

    def get_selected_project(self) -> Optional[Dict[str, Any]]:
        sel = self.projects_list.curselection()
        if not sel:
            return None
        idx = sel[0]
        projects = self.data.get("projects", [])
        if 0 <= idx < len(projects):
            return projects[idx]
        return None

    def on_project_select(self):
        proj = self.get_selected_project()
        if proj:
            self.data["selected_project_id"] = proj["id"]
            self.save_data()
            self.apply_filters_and_render()

    def add_project(self):
        name = tk.simpledialog.askstring("New Project", "Enter project name:")
        if not name:
            return
        new_proj = {"id": str(uuid.uuid4()), "name": name.strip(), "tasks": []}
        self.data["projects"].append(new_proj)
        self.data["selected_project_id"] = new_proj["id"]
        self.refresh_projects_list()
        self.restore_selection()
        self.save_data()
        self.apply_filters_and_render()

    def rename_project(self):
        proj = self.get_selected_project()
        if not proj:
            messagebox.showinfo("Projects", "Select a project to rename.")
            return
        name = tk.simpledialog.askstring("Rename Project", "Enter new name:", initialvalue=proj.get("name", ""))
        if not name:
            return
        proj["name"] = name.strip()
        self.refresh_projects_list()
        self.save_data()

    def delete_project(self):
        proj = self.get_selected_project()
        if not proj:
            messagebox.showinfo("Projects", "Select a project to delete.")
            return
        if not messagebox.askyesno("Delete Project", f"Delete project '{proj.get('name','')}'? This cannot be undone."):
            return
        self.data["projects"] = [p for p in self.data.get("projects", []) if p["id"] != proj["id"]]
        self.data["selected_project_id"] = self.data["projects"][0]["id"] if self.data["projects"] else None
        self.refresh_projects_list()
        self.restore_selection()
        self.save_data()
        self.apply_filters_and_render()

    # Task operations
    def add_task(self, default_status: str = "To Do"):
        proj = self.get_selected_project()
        if not proj:
            messagebox.showinfo("Tasks", "Create or select a project first.")
            return
        dlg = TaskDialog(self, proj, task=None)
        self.wait_window(dlg)
        if dlg.result:
            t = dlg.result
            new_task = {
                "id": str(uuid.uuid4()),
                "title": t["title"],
                "description": t.get("description", ""),
                "priority": t.get("priority", "Medium"),
                "tags": t.get("tags", []),
                "due_date": t.get("due_date", ""),
                "status": t.get("status", default_status) or default_status,
                "dependencies": t.get("dependencies", []),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            if self.would_create_cycle(proj, new_task["id"], new_task["dependencies"]):
                messagebox.showerror("Dependencies", "The selected dependencies would create a cycle.")
                return
            proj["tasks"].append(new_task)
            self.save_data()
            self.apply_filters_and_render()

    def find_task_by_id(self, proj: Dict[str, Any], task_id: str) -> Optional[Dict[str, Any]]:
        for t in proj.get("tasks", []):
            if t["id"] == task_id:
                return t
        return None

    def on_edit_selected(self, status: str):
        tid = self.get_selected_task_id(status)
        if not tid:
            return
        self.edit_task_by_id(tid)

    def edit_task_by_id(self, task_id: str):
        proj = self.get_selected_project()
        if not proj:
            return
        task = self.find_task_by_id(proj, task_id)
        if not task:
            return
        dlg = TaskDialog(self, proj, task=task)
        self.wait_window(dlg)
        if not dlg.result:
            return
        updated = dlg.result
        # Check dependencies for cycles
        if self.would_create_cycle(proj, task["id"], updated.get("dependencies", [])):
            messagebox.showerror("Dependencies", "The selected dependencies would create a cycle.")
            return
        # Prevent setting to Done if deps incomplete
        if updated.get("status") == "Done" and not self.dependencies_satisfied(proj, updated.get("dependencies", [])):
            messagebox.showerror("Dependencies", "Cannot mark Done: one or more dependencies are not completed.")
            return
        task.update(updated)
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.save_data()
        self.apply_filters_and_render()

    def delete_task_by_id(self, task_id: str):
        proj = self.get_selected_project()
        if not proj:
            return
        task = self.find_task_by_id(proj, task_id)
        if not task:
            return
        # Confirm and warn if other tasks depend on this task
        dependents = [t for t in proj.get("tasks", []) if task_id in t.get("dependencies", [])]
        warn = "Other tasks depend on this task. They will lose this dependency.\n\n" if dependents else ""
        if not messagebox.askyesno("Delete Task", warn + f"Delete '{task.get('title','')}'?"):
            return
        # Remove from dependencies of others
        for t in proj.get("tasks", []):
            if task_id in t.get("dependencies", []):
                t["dependencies"] = [d for d in t["dependencies"] if d != task_id]
        proj["tasks"] = [t for t in proj.get("tasks", []) if t["id"] != task_id]
        self.save_data()
        self.apply_filters_and_render()

    def set_task_status(self, task_id: str, new_status: str):
        proj = self.get_selected_project()
        if not proj:
            return
        task = self.find_task_by_id(proj, task_id)
        if not task:
            return
        if new_status == "Done":
            # All dependencies must be Done
            if not self.dependencies_satisfied(proj, task.get("dependencies", [])):
                messagebox.showerror("Dependencies", "Cannot mark Done: one or more dependencies are not completed.")
                return
        task["status"] = new_status
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.save_data()
        self.apply_filters_and_render()

    def dependencies_satisfied(self, proj: Dict[str, Any], dep_ids: List[str]) -> bool:
        for dep in dep_ids:
            t = self.find_task_by_id(proj, dep)
            if t and t.get("status") != "Done":
                return False
        return True

    def would_create_cycle(self, proj: Dict[str, Any], task_id: str, new_deps: List[str]) -> bool:
        # Build adjacency list: task -> dependencies
        adj: Dict[str, List[str]] = {}
        nodes = set()
        for t in proj.get("tasks", []):
            nodes.add(t["id"])
        nodes.add(task_id)
        for t in proj.get("tasks", []):
            if t["id"] == task_id:
                adj[t["id"]] = list(new_deps)
            else:
                adj[t["id"]] = list(t.get("dependencies", []))
        # If any dependency can reach task_id, adding edge creates cycle
        def dfs(start: str, target: str, visited: set) -> bool:
            if start == target:
                return True
            visited.add(start)
            for nb in adj.get(start, []):
                if nb not in visited:
                    if dfs(nb, target, visited):
                        return True
            return False
        for dep in new_deps:
            if dfs(dep, task_id, set()):
                return True
        # Also guard against self-dependency
        if task_id in new_deps:
            return True
        return False

    # Rendering and filtering
    def clear_filters(self):
        self.search_var.set("")
        self.status_filter.set("All")
        self.priority_filter.set("All")
        self.tags_filter.set("")
        self.due_from_var.set("")
        self.due_to_var.set("")
        self.apply_filters_and_render()

    def apply_filters_and_render(self):
        proj = self.get_selected_project()
        for s in STATUSES:
            lb = self.columns[s]["listbox"]
            lb.delete(0, tk.END)
            self.columns[s]["index_to_task_id"] = []
        if not proj:
            self.update_stats(None)
            return
        tasks = proj.get("tasks", [])
        filtered = self.filter_tasks(tasks)
        # By status filter
        status_sel = self.status_filter.get()
        status_sets = {s: [] for s in STATUSES}
        for t in filtered:
            s = t.get("status")
            if status_sel == "All" or s == status_sel:
                status_sets[s].append(t)
        # Sort within columns: by due date asc, then priority (High first), then title
        pr_rank = {"High": 0, "Medium": 1, "Low": 2}
        def sort_key(t):
            d = safe_parse_date(t.get("due_date", "")) or date.max
            return (d, pr_rank.get(t.get("priority"), 1), t.get("title", ""))
        for s in STATUSES:
            status_sets[s].sort(key=sort_key)
            for t in status_sets[s]:
                self.columns[s]["listbox"].insert(tk.END, format_task_line(t))
                self.columns[s]["index_to_task_id"].append(t["id"])
        self.update_stats(proj)

    def filter_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        txt = self.search_var.get().strip().lower()
        pr = self.priority_filter.get()
        tag_filter = [x.strip().lower() for x in self.tags_filter.get().split(",") if x.strip()]
        d_from = safe_parse_date(self.due_from_var.get().strip())
        d_to = safe_parse_date(self.due_to_var.get().strip())

        def matches(t: Dict[str, Any]) -> bool:
            if txt:
                hay = f"{t.get('title','')}\n{t.get('description','')}\n{' '.join(t.get('tags',[]))}".lower()
                if txt not in hay:
                    return False
            if pr != "All" and t.get("priority") != pr:
                return False
            if tag_filter:
                tags = [x.lower() for x in t.get("tags", [])]
                for tf in tag_filter:
                    if tf not in tags:
                        return False
            if d_from:
                d = safe_parse_date(t.get("due_date", ""))
                if not d or d < d_from:
                    return False
            if d_to:
                d = safe_parse_date(t.get("due_date", ""))
                if not d or d > d_to:
                    return False
            return True

        return [t for t in tasks if matches(t)]

    def update_stats(self, proj: Optional[Dict[str, Any]]):
        if not proj:
            self.stat_todo.set("To Do: 0")
            self.stat_prog.set("In Progress: 0")
            self.stat_done.set("Done: 0")
            self.stat_overdue.set("Overdue: 0")
            self.stat_completion.set("Completion: 0%")
            return
        tasks = proj.get("tasks", [])
        counts = {s: 0 for s in STATUSES}
        overdue = 0
        for t in tasks:
            counts[t.get("status", "To Do")] = counts.get(t.get("status", "To Do"), 0) + 1
            d = safe_parse_date(t.get("due_date", ""))
            if d and d < date.today() and t.get("status") != "Done":
                overdue += 1
        total = len(tasks) or 1
        completion = int(round(100 * (counts.get("Done", 0) / total)))
        self.stat_todo.set(f"To Do: {counts.get('To Do', 0)}")
        self.stat_prog.set(f"In Progress: {counts.get('In Progress', 0)}")
        self.stat_done.set(f"Done: {counts.get('Done', 0)}")
        self.stat_overdue.set(f"Overdue: {overdue}")
        self.stat_completion.set(f"Completion: {completion}%")

    # Context menu handling
    def on_context_menu(self, event, status: str):
        lb = self.columns[status]["listbox"]
        try:
            index = lb.nearest(event.y)
            lb.selection_clear(0, tk.END)
            lb.selection_set(index)
            self.menu_context = {"status": status, "index": index}
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def menu_edit(self):
        status = self.menu_context.get("status")
        index = self.menu_context.get("index")
        if status is None or index is None:
            return
        tid = self.get_task_id_by_index(status, index)
        if tid:
            self.edit_task_by_id(tid)

    def menu_delete(self):
        status = self.menu_context.get("status")
        index = self.menu_context.get("index")
        if status is None or index is None:
            return
        tid = self.get_task_id_by_index(status, index)
        if tid:
            self.delete_task_by_id(tid)

    def menu_move(self, target_status: str):
        status = self.menu_context.get("status")
        index = self.menu_context.get("index")
        if status is None or index is None:
            return
        tid = self.get_task_id_by_index(status, index)
        if tid:
            self.set_task_status(tid, target_status)

    def get_selected_task_id(self, status: str) -> Optional[str]:
        lb = self.columns[status]["listbox"]
        sel = lb.curselection()
        if not sel:
            return None
        idx = sel[0]
        return self.get_task_id_by_index(status, idx)

    def get_task_id_by_index(self, status: str, idx: int) -> Optional[str]:
        ids = self.columns[status]["index_to_task_id"]
        if 0 <= idx < len(ids):
            return ids[idx]
        return None


if __name__ == "__main__":
    app = App()
    app.mainloop()
