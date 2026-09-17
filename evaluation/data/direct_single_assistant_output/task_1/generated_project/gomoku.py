#!/usr/bin/env python3
"""
Gomoku (Five-in-a-Row) with Tkinter GUI and AI (3 difficulty levels)

How to run:
    python3 gomoku.py

Controls:
    - Click on the board to place a stone (Human plays Black by default).
    - Use the Difficulty radio buttons to choose AI level (Easy/Medium/Hard).
    - Toggle "AI First" if you want the AI (White) to open the game, then click Restart.
    - Click Restart to start a new game with the selected options.
    - Status bar shows turn, winner, or draw.

AI levels:
    - Easy: random among plausible candidate moves.
    - Medium: greedy 1-ply search using a heuristic (also blocks/wins immediately).
    - Hard: alpha-beta search with depth and candidate pruning + heuristic evaluation.

Notes:
    - Board size defaults to 15x15. Adjust BOARD_SIZE if desired.
    - The AI uses candidate move generation near existing stones for performance.
    - Hard level search depth is modest to keep moves responsive on typical machines.

Author: ChatGPT
"""

import tkinter as tk
from tkinter import ttk
import random
from typing import List, Tuple, Optional

# Game settings
BOARD_SIZE = 15
WIN_LEN = 5
MARGIN = 30  # canvas margin in pixels
GRID_PIXELS = 30  # pixel distance between intersections
STONE_RADIUS = 12

# AI settings
EASY = "Easy"
MEDIUM = "Medium"
HARD = "Hard"
DIFFICULTIES = [EASY, MEDIUM, HARD]

HARD_MAX_DEPTH = 3  # effective ply for the AI side; may adjust based on performance
MEDIUM_MAX_DEPTH = 1

# Candidate move pruning
CANDIDATE_RADIUS = 2  # consider empty cells within this manhattan radius of stones
MAX_CANDIDATES_HARD = 14
MAX_CANDIDATES_MEDIUM = 18

# Players
EMPTY = 0
BLACK = 1   # Human by default
WHITE = -1  # AI by default

# Evaluation weights (tunable)
# We score line patterns for a given player p in each direction.
# open_k: k in a row with two open ends
# semiopen_k: k in a row with one open end
WEIGHTS = {
    ("open", 5): 1000000,   # immediate win
    ("semi", 5): 500000,    # win even if semi-open (still winning state)
    ("open", 4): 20000,
    ("semi", 4): 5000,
    ("open", 3): 1000,
    ("semi", 3): 200,
    ("open", 2): 50,
    ("semi", 2): 10,
}

class Gomoku:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Gomoku with AI")

        self.board: List[List[int]] = [[EMPTY for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.current_player: int = BLACK
        self.game_over: bool = False
        self.last_move: Optional[Tuple[int, int]] = None

        self.difficulty = tk.StringVar(value=MEDIUM)
        self.ai_first = tk.BooleanVar(value=False)

        # Layout
        self._build_ui()
        self._reset_game()

    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        ttk.Label(top, text="Difficulty:").pack(side=tk.LEFT, padx=(0, 6))
        for level in DIFFICULTIES:
            ttk.Radiobutton(top, text=level, value=level, variable=self.difficulty).pack(side=tk.LEFT)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Checkbutton(top, text="AI First (White)", variable=self.ai_first).pack(side=tk.LEFT)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(top, text="Restart", command=self._reset_game).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Black (You) to move")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w").pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0,6))

        canvas_size = MARGIN*2 + GRID_PIXELS*(BOARD_SIZE-1)
        self.canvas = tk.Canvas(self.root, width=canvas_size, height=canvas_size, bg="#f2d5a9", highlightthickness=0)
        self.canvas.pack(side=tk.TOP, padx=8, pady=8)
        self.canvas.bind("<Button-1>", self._on_click)

        self._draw_grid()

    def _reset_game(self):
        self.board = [[EMPTY for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.current_player = BLACK if not self.ai_first.get() else WHITE
        self.game_over = False
        self.last_move = None
        self._redraw()
        if self.current_player == WHITE:
            self.status_var.set("AI (White) to move...")
            self.root.after(200, self._ai_move)
        else:
            self.status_var.set("Black (You) to move")

    def _draw_grid(self):
        self.canvas.delete("grid")
        size = MARGIN*2 + GRID_PIXELS*(BOARD_SIZE-1)
        # outer border
        self.canvas.create_rectangle(MARGIN-2, MARGIN-2, size-MARGIN+2, size-MARGIN+2, outline="#8b5a2b", tags="grid")
        # star points common for 15x15
        star_points = {3, 7, 11} if BOARD_SIZE == 15 else set()
        for i in range(BOARD_SIZE):
            x0 = MARGIN + i*GRID_PIXELS
            y0 = MARGIN
            y1 = MARGIN + (BOARD_SIZE-1)*GRID_PIXELS
            self.canvas.create_line(x0, y0, x0, y1, fill="#333", tags="grid")

            y = MARGIN + i*GRID_PIXELS
            x0 = MARGIN
            x1 = MARGIN + (BOARD_SIZE-1)*GRID_PIXELS
            self.canvas.create_line(x0, y, x1, y, fill="#333", tags="grid")

        # star points
        for i in star_points:
            for j in star_points:
                cx, cy = self._cell_to_xy(i, j)
                r = 3
                self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill="#333", outline="", tags="grid")

    def _redraw(self):
        self.canvas.delete("stone")
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if self.board[r][c] != EMPTY:
                    self._draw_stone(r, c, self.board[r][c])

    def _draw_stone(self, r: int, c: int, player: int):
        cx, cy = self._cell_to_xy(c, r)
        color = "black" if player == BLACK else "white"
        outline = "#111" if player == BLACK else "#bbb"
        self.canvas.create_oval(cx-STONE_RADIUS, cy-STONE_RADIUS, cx+STONE_RADIUS, cy+STONE_RADIUS,
                                fill=color, outline=outline, width=2, tags="stone")
        # highlight last move
        if self.last_move == (r, c):
            self.canvas.create_rectangle(cx-STONE_RADIUS-2, cy-STONE_RADIUS-2, cx+STONE_RADIUS+2, cy+STONE_RADIUS+2,
                                         outline="#e74c3c", width=2, tags="stone")

    def _cell_to_xy(self, col: int, row: int) -> Tuple[int, int]:
        x = MARGIN + col * GRID_PIXELS
        y = MARGIN + row * GRID_PIXELS
        return x, y

    def _xy_to_cell(self, x: int, y: int) -> Optional[Tuple[int, int]]:
        # Find nearest intersection
        if x < MARGIN - GRID_PIXELS/2 or y < MARGIN - GRID_PIXELS/2:
            return None
        col = round((x - MARGIN) / GRID_PIXELS)
        row = round((y - MARGIN) / GRID_PIXELS)
        if 0 <= col < BOARD_SIZE and 0 <= row < BOARD_SIZE:
            return row, col
        return None

    def _on_click(self, event):
        if self.game_over or self.current_player != BLACK:
            return
        cell = self._xy_to_cell(event.x, event.y)
        if not cell:
            return
        r, c = cell
        if self.board[r][c] != EMPTY:
            return
        self._place_stone(r, c, BLACK)
        if self._check_game_end(r, c):
            return
        # AI move
        self.status_var.set("AI (White) to move...")
        self.root.after(150, self._ai_move)

    def _place_stone(self, r: int, c: int, player: int):
        self.board[r][c] = player
        self.last_move = (r, c)
        self._draw_stone(r, c, player)
        self.current_player = -player

    def _check_game_end(self, r: int, c: int) -> bool:
        winner = check_winner(self.board, r, c)
        if winner != EMPTY:
            self.game_over = True
            if winner == BLACK:
                self.status_var.set("You win! (Black)")
            else:
                self.status_var.set("AI wins! (White)")
            return True
        if all(self.board[i][j] != EMPTY for i in range(BOARD_SIZE) for j in range(BOARD_SIZE)):
            self.game_over = True
            self.status_var.set("Draw.")
            return True
        # Update status for next player
        if self.current_player == BLACK:
            self.status_var.set("Black (You) to move")
        else:
            self.status_var.set("AI (White) to move...")
        return False

    # --------------------- AI ---------------------
    def _ai_move(self):
        if self.game_over or self.current_player != WHITE:
            return
        level = self.difficulty.get()
        if level == EASY:
            r, c = ai_move_easy(self.board)
        elif level == MEDIUM:
            r, c = ai_move_medium(self.board)
        else:
            r, c = ai_move_hard(self.board)
        if r is None:
            # Fallback: random empty
            empties = [(i, j) for i in range(BOARD_SIZE) for j in range(BOARD_SIZE) if self.board[i][j] == EMPTY]
            if not empties:
                return
            r, c = random.choice(empties)
        self._place_stone(r, c, WHITE)
        self._check_game_end(r, c)

# ----------------- Core logic -----------------

def check_winner(board: List[List[int]], r: int, c: int) -> int:
    player = board[r][c]
    if player == EMPTY:
        return EMPTY
    directions = [(1,0), (0,1), (1,1), (1,-1)]
    for dr, dc in directions:
        count = 1
        # forward
        i, j = r+dr, c+dc
        while 0 <= i < BOARD_SIZE and 0 <= j < BOARD_SIZE and board[i][j] == player:
            count += 1
            i += dr
            j += dc
        # backward
        i, j = r-dr, c-dc
        while 0 <= i < BOARD_SIZE and 0 <= j < BOARD_SIZE and board[i][j] == player:
            count += 1
            i -= dr
            j -= dc
        if count >= WIN_LEN:
            return player
    return EMPTY

# ------------- AI Helpers -------------

def generate_candidates(board: List[List[int]], radius: int = CANDIDATE_RADIUS) -> List[Tuple[int,int]]:
    stones = [(r, c) for r in range(BOARD_SIZE) for c in range(BOARD_SIZE) if board[r][c] != EMPTY]
    if not stones:
        mid = BOARD_SIZE // 2
        return [(mid, mid)]
    cand = set()
    for r, c in stones:
        for i in range(max(0, r - radius), min(BOARD_SIZE, r + radius + 1)):
            for j in range(max(0, c - radius), min(BOARD_SIZE, c + radius + 1)):
                if board[i][j] == EMPTY:
                    cand.add((i, j))
    # If somehow we have no candidates (shouldn't happen), return all empties
    if not cand:
        cand = {(i, j) for i in range(BOARD_SIZE) for j in range(BOARD_SIZE) if board[i][j] == EMPTY}
    return list(cand)


def evaluate_board(board: List[List[int]]) -> int:
    # Positive is good for WHITE (AI), negative for BLACK (Human)
    return evaluate_for_player(board, WHITE) - evaluate_for_player(board, BLACK)


def evaluate_for_player(board: List[List[int]], player: int) -> int:
    # Sum pattern scores across the board for the given player
    total = 0
    directions = [(1,0), (0,1), (1,1), (1,-1)]
    visited = set()  # Avoid recounting the same segment

    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if board[r][c] != player:
                continue
            for dr, dc in directions:
                key = (r, c, dr, dc)
                if key in visited:
                    continue
                # Only start at the beginning of a sequence
                prev_r, prev_c = r - dr, c - dc
                if 0 <= prev_r < BOARD_SIZE and 0 <= prev_c < BOARD_SIZE and board[prev_r][prev_c] == player:
                    continue
                # Walk forward to count consecutive stones and determine openness
                k = 0
                i, j = r, c
                while 0 <= i < BOARD_SIZE and 0 <= j < BOARD_SIZE and board[i][j] == player:
                    visited.add((i, j, dr, dc))
                    k += 1
                    i += dr
                    j += dc
                open_ends = 0
                if 0 <= i < BOARD_SIZE and 0 <= j < BOARD_SIZE and board[i][j] == EMPTY:
                    open_ends += 1
                # Check the cell before the sequence start
                i2, j2 = r - dr, c - dc
                if 0 <= i2 < BOARD_SIZE and 0 <= j2 < BOARD_SIZE and board[i2][j2] == EMPTY:
                    open_ends += 1

                if k >= WIN_LEN:
                    total += WEIGHTS.get(("open", 5), 1000000)
                else:
                    if open_ends == 2:
                        total += WEIGHTS.get(("open", k), 0)
                    elif open_ends == 1:
                        total += WEIGHTS.get(("semi", k), 0)
                    # closed ends get no score
    return total


def order_moves(board: List[List[int]], moves: List[Tuple[int,int]]) -> List[Tuple[int,int]]:
    # Simple move ordering by placing stone for AI and scoring delta
    scored = []
    for r, c in moves:
        board[r][c] = WHITE
        score = evaluate_board(board)
        board[r][c] = EMPTY
        scored.append(((r, c), score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [pos for pos, _ in scored]


def immediate_win_or_block(board: List[List[int]], us: int, them: int) -> Optional[Tuple[int,int]]:
    # Check if we can win now
    for r, c in generate_candidates(board, radius=1):
        if board[r][c] != EMPTY:
            continue
        board[r][c] = us
        if check_winner(board, r, c) == us:
            board[r][c] = EMPTY
            return (r, c)
        board[r][c] = EMPTY
    # Block opponent's immediate win
    for r, c in generate_candidates(board, radius=1):
        if board[r][c] != EMPTY:
            continue
        board[r][c] = them
        if check_winner(board, r, c) == them:
            board[r][c] = EMPTY
            return (r, c)
        board[r][c] = EMPTY
    return None


def ai_move_easy(board: List[List[int]]) -> Tuple[Optional[int], Optional[int]]:
    # Choose randomly among candidates
    move = immediate_win_or_block(board, WHITE, BLACK)
    if move:
        return move
    cand = generate_candidates(board)
    empties = [(r, c) for (r, c) in cand if board[r][c] == EMPTY]
    if not empties:
        return None, None
    return random.choice(empties)


def ai_move_medium(board: List[List[int]]) -> Tuple[Optional[int], Optional[int]]:
    # Greedy 1-ply: pick move maximizing evaluated board after our move
    win_block = immediate_win_or_block(board, WHITE, BLACK)
    if win_block:
        return win_block
    cand = generate_candidates(board)
    # order by quick heuristic
    ordered = order_moves(board, cand)
    best_score = -float('inf')
    best_move = None
    for r, c in ordered[:MAX_CANDIDATES_MEDIUM]:
        if board[r][c] != EMPTY:
            continue
        board[r][c] = WHITE
        score = evaluate_board(board)
        board[r][c] = EMPTY
        if score > best_score:
            best_score = score
            best_move = (r, c)
    if best_move:
        return best_move
    # fallback
    return ai_move_easy(board)


def ai_move_hard(board: List[List[int]]) -> Tuple[Optional[int], Optional[int]]:
    # Alpha-beta with depth-limited search
    win_block = immediate_win_or_block(board, WHITE, BLACK)
    if win_block:
        return win_block

    cand = generate_candidates(board)
    ordered = order_moves(board, cand)[:MAX_CANDIDATES_HARD]

    best_val = -float('inf')
    best_move = None

    alpha = -float('inf')
    beta = float('inf')

    for r, c in ordered:
        if board[r][c] != EMPTY:
            continue
        board[r][c] = WHITE
        val = -negamax(board, depth=HARD_MAX_DEPTH-1, alpha=-beta, beta=-alpha, player=-WHITE)
        board[r][c] = EMPTY
        if val > best_val:
            best_val = val
            best_move = (r, c)
        alpha = max(alpha, val)
        if alpha >= beta:
            break

    if best_move:
        return best_move
    # fallback to medium
    return ai_move_medium(board)


def negamax(board: List[List[int]], depth: int, alpha: float, beta: float, player: int) -> int:
    # Terminal check based on last move is not directly available here; we rely on depth and heuristic.
    if depth == 0:
        eval_val = evaluate_board(board)
        return eval_val if player == WHITE else -eval_val

    # Check for immediate winning moves for the side to move (pruning)
    winner_move = immediate_win_or_block(board, player, -player)
    if winner_move:
        r, c = winner_move
        board[r][c] = player
        val = evaluate_board(board)
        board[r][c] = EMPTY
        return val if player == WHITE else -val

    cand = generate_candidates(board)
    # order for the current perspective: try moves best for WHITE
    ordered = order_moves(board, cand)

    best = -float('inf')
    for r, c in ordered[:MAX_CANDIDATES_HARD]:
        if board[r][c] != EMPTY:
            continue
        board[r][c] = player
        # Check immediate win with this move to cut off
        if check_winner(board, r, c) == player:
            board[r][c] = EMPTY
            return 999999 if player == WHITE else -999999
        val = -negamax(board, depth-1, -beta, -alpha, -player)
        board[r][c] = EMPTY
        if val > best:
            best = val
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    # If no moves lead to anything better, return evaluation
    if best == -float('inf'):
        eval_val = evaluate_board(board)
        return eval_val if player == WHITE else -eval_val
    return best

# ----------------- Main -----------------

def main():
    root = tk.Tk()
    # Use ttk theme for nicer widgets if available
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    app = Gomoku(root)
    root.mainloop()

if __name__ == "__main__":
    main()
