from __future__ import annotations

import tkinter
import tkinter.ttk as ttk
from typing import Callable, Optional

STONE_RADIUS_FRAC = 0.38  # fraction of cell size
LAST_MOVE_MARKER_FRAC = 0.18
WIN_LINE_WIDTH = 4


class GomokuView:
    def __init__(self, root: tkinter.Tk, board_size: int = 15,
                 on_intersection_click: Callable[[int, int], None] | None = None,
                 on_new_game: Callable[[], None] | None = None,
                 on_quit: Callable[[], None] | None = None,
                 on_difficulty_change: Callable[[str], None] | None = None,
                 on_starter_change: Callable[[str], None] | None = None) -> None:
        self.root = root
        self.board_size = board_size
        self.on_intersection_click = on_intersection_click
        self.on_new_game = on_new_game
        self.on_quit = on_quit
        self.on_difficulty_change = on_difficulty_change
        self.on_starter_change = on_starter_change

        self._board_enabled = True
        self._current_difficulty = "Medium"
        self._current_starter = "Human"

        self.main_frame = ttk.Frame(root)
        self.main_frame.pack(fill="both", expand=True)

        self.left_frame = ttk.Frame(self.main_frame)
        self.left_frame.pack(side="left", fill="both", expand=True)
        self.right_frame = ttk.Frame(self.main_frame, width=240)
        self.right_frame.pack(side="right", fill="y")

        # Canvas for board
        self.canvas = tkinter.Canvas(self.left_frame, background="#EEC97F", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)

        # Bind resize to re-render
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Button-1>", self._on_click)

        # Controls
        self.controls = ttk.Frame(self.right_frame, padding=10)
        self.controls.pack(fill="y", expand=False)

        self.title_label = ttk.Label(self.controls, text="Gomoku", font=("Arial", 16, "bold"))
        self.title_label.pack(pady=(0, 10))

        self.status_label = ttk.Label(self.controls, text="Status: Ready", wraplength=200)
        self.status_label.pack(pady=(0, 10))

        # Difficulty
        ttk.Label(self.controls, text="Difficulty").pack(anchor="w")
        self.difficulty_var = tkinter.StringVar(value=self._current_difficulty)
        self.difficulty_combo = ttk.Combobox(self.controls, textvariable=self.difficulty_var,
                                             values=["Easy", "Medium", "Hard"], state="readonly")
        self.difficulty_combo.pack(fill="x", pady=(0, 8))
        self.difficulty_combo.bind("<<ComboboxSelected>>", self._difficulty_selected)

        # Starter
        ttk.Label(self.controls, text="Starter").pack(anchor="w")
        self.starter_var = tkinter.StringVar(value=self._current_starter)
        self.starter_combo = ttk.Combobox(self.controls, textvariable=self.starter_var,
                                          values=["Human", "AI"], state="readonly")
        self.starter_combo.pack(fill="x", pady=(0, 8))
        self.starter_combo.bind("<<ComboboxSelected>>", self._starter_selected)

        # Buttons
        self.new_game_btn = ttk.Button(self.controls, text="New Game", command=self._on_new)
        self.new_game_btn.pack(fill="x", pady=(8, 4))
        self.quit_btn = ttk.Button(self.controls, text="Quit", command=self._on_quit)
        self.quit_btn.pack(fill="x", pady=(4, 8))

        self.info_label = ttk.Label(self.controls, text="Turn: --\nDifficulty: Medium\nStarter: Human", justify="left")
        self.info_label.pack(pady=8)

        # Internal drawing state
        self._last_board = [[0 for _ in range(board_size)] for _ in range(board_size)]
        self._last_move = None
        self._winning_line = None

        # initial render
        self.render_board(self._last_board)

    def _on_new(self) -> None:
        if self.on_new_game:
            self.on_new_game()

    def _on_quit(self) -> None:
        if self.on_quit:
            self.on_quit()

    def _difficulty_selected(self, event=None) -> None:
        value = self.difficulty_var.get()
        self._current_difficulty = value
        self.set_difficulty_display(value)
        if self.on_difficulty_change:
            self.on_difficulty_change(value)

    def _starter_selected(self, event=None) -> None:
        value = self.starter_var.get()
        self._current_starter = value
        self.set_starter_display(value)
        if self.on_starter_change:
            self.on_starter_change(value)

    def _on_resize(self, event) -> None:
        self.render_board(self._last_board, self._last_move, self._winning_line)

    def _grid_geometry(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        size = min(w, h)
        margin = int(size * 0.06) + 16  # margins around the grid
        grid_size = size - 2 * margin
        if grid_size <= 0:
            grid_size = min(w, h) - 2 * 20
        cell = grid_size / (self.board_size - 1)
        ox = (w - grid_size) / 2
        oy = (h - grid_size) / 2
        return ox, oy, cell, grid_size

    def _snap_to_intersection(self, x: float, y: float) -> tuple[int, int] | None:
        ox, oy, cell, _ = self._grid_geometry()
        # find closest row, col
        col = round((x - ox) / cell)
        row = round((y - oy) / cell)
        if row < 0 or row >= self.board_size or col < 0 or col >= self.board_size:
            return None
        # distance to exact intersection
        cx = ox + col * cell
        cy = oy + row * cell
        dist2 = (cx - x) ** 2 + (cy - y) ** 2
        radius = cell * 0.45
        if dist2 <= radius * radius:
            return (int(row), int(col))
        return None

    def _on_click(self, event) -> None:
        if not self._board_enabled:
            self.flash_invalid_click()
            return
        snap = self._snap_to_intersection(event.x, event.y)
        if snap is None:
            self.flash_invalid_click()
            return
        r, c = snap
        if self.on_intersection_click:
            self.on_intersection_click(r, c)

    def render_board(self, board: list[list[int]], last_move: tuple[int, int] | None = None,
                     winning_line: list[tuple[int, int]] | None = None) -> None:
        self._last_board = [row[:] for row in board]
        self._last_move = last_move
        self._winning_line = None if winning_line is None else list(winning_line)

        self.canvas.delete("all")
        ox, oy, cell, grid_size = self._grid_geometry()
        # draw grid
        for i in range(self.board_size):
            x0 = ox
            x1 = ox + grid_size
            y = oy + i * cell
            self.canvas.create_line(x0, y, x1, y, fill="#6C4E16")
            y0 = oy
            y1 = oy + grid_size
            x = ox + i * cell
            self.canvas.create_line(x, y0, x, y1, fill="#6C4E16")

        # draw star points for aesthetics (standard Go board points on 15x15)
        star_points = [(3, 3), (3, 11), (7, 7), (11, 3), (11, 11)]
        for (r, c) in star_points:
            cx = ox + c * cell
            cy = oy + r * cell
            rad = max(2, int(cell * 0.07))
            self.canvas.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, fill="#6C4E16", outline="")

        # draw stones
        stone_rad = cell * STONE_RADIUS_FRAC
        for r in range(self.board_size):
            for c in range(self.board_size):
                v = board[r][c]
                if v == 0:
                    continue
                cx = ox + c * cell
                cy = oy + r * cell
                color = "#000000" if v == 1 else "#FFFFFF"
                outline = "#222222" if v == 1 else "#DDDDDD"
                self.canvas.create_oval(cx - stone_rad, cy - stone_rad, cx + stone_rad, cy + stone_rad,
                                        fill=color, outline=outline, width=2)

        # winning line highlight
        if winning_line:
            for (r, c) in winning_line:
                cx = ox + c * cell
                cy = oy + r * cell
                rad = stone_rad * 0.6
                self.canvas.create_oval(cx - rad, cy - rad, cx + rad, cy + rad,
                                        outline="#FF3333", width=WIN_LINE_WIDTH)

        # last move marker
        if last_move is not None:
            r, c = last_move
            cx = ox + c * cell
            cy = oy + r * cell
            rad = stone_rad * (1.0 - LAST_MOVE_MARKER_FRAC)
            self.canvas.create_oval(cx - rad, cy - rad, cx + rad, cy + rad,
                                    outline="#FFD000", width=3)

    def set_status(self, text: str) -> None:
        self.status_label.config(text=text)

    def set_turn(self, is_human_turn: bool, color: int) -> None:
        who = "Human" if is_human_turn else "AI"
        colname = "Black" if color == 1 else "White"
        self.info_label.config(text=f"Turn: {who} ({colname})\nDifficulty: {self._current_difficulty}\nStarter: {self._current_starter}")

    def set_difficulty_display(self, difficulty: str) -> None:
        self._current_difficulty = difficulty
        self.difficulty_var.set(difficulty)
        # Keep the current "Turn:" line intact; update the rest
        current_turn_line = self.info_label.cget("text").split("\n")[0]
        self.info_label.config(text=f"{current_turn_line}\nDifficulty: {self._current_difficulty}\nStarter: {self._current_starter}")

    def set_starter_display(self, starter: str) -> None:
        self._current_starter = starter
        self.starter_var.set(starter)
        # Keep the current "Turn:" line intact; update the rest
        current_turn_line = self.info_label.cget("text").split("\n")[0]
        self.info_label.config(text=f"{current_turn_line}\nDifficulty: {self._current_difficulty}\nStarter: {self._current_starter}")

    def enable_board(self) -> None:
        self._board_enabled = True
        self.canvas.config(cursor="arrow")

    def disable_board(self) -> None:
        self._board_enabled = False
        self.canvas.config(cursor="watch")

    def flash_invalid_click(self) -> None:
        # Brief non-intrusive feedback: slight status flash and message
        orig_bg = self.status_label.cget("background")
        orig_text = self.status_label.cget("text")
        try:
            self.status_label.config(background="#FFEEEE")
        except Exception:
            pass
        try:
            self.set_status("Invalid: click on an empty intersection within the grid.")
        except Exception:
            pass

        def restore():
            try:
                self.status_label.config(background=orig_bg)
            except Exception:
                pass
            try:
                self.set_status(orig_text)
            except Exception:
                pass

        # restore after short delay
        self.root.after(600, restore)