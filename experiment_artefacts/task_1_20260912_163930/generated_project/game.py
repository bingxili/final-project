from __future__ import annotations

from typing import List, Optional, Tuple


Board = List[List[int]]  # 0 empty, 1 black, 2 white


def check_winner(board: Board, row: int, col: int) -> tuple[int | None, list[tuple[int, int]] | None]:
    """
    Check if the stone at (row, col) completes a five-in-a-row (exactly five).
    Returns (winner_color or None, winning_line or None)

    Notes:
    - Only sequences of exactly five contiguous stones that include (row, col)
      are considered a win. Longer contiguous sequences (overlines) are ignored.
    """
    color = board[row][col]
    if color == 0:
        return (None, None)

    directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
    size = len(board)
    for dr, dc in directions:
        neg_coords: list[tuple[int, int]] = []
        pos_coords: list[tuple[int, int]] = []

        # extend negative direction
        r, c = row - dr, col - dc
        while 0 <= r < size and 0 <= c < size and board[r][c] == color:
            neg_coords.append((r, c))
            r -= dr
            c -= dc
        # Check if the sequence can be extended further on the negative end
        neg_extendable = (0 <= r < size and 0 <= c < size and board[r][c] == color)

        # extend positive direction
        r, c = row + dr, col + dc
        while 0 <= r < size and 0 <= c < size and board[r][c] == color:
            pos_coords.append((r, c))
            r += dr
            c += dc
        # Check if the sequence can be extended further on the positive end
        pos_extendable = (0 <= r < size and 0 <= c < size and board[r][c] == color)

        total = 1 + len(neg_coords) + len(pos_coords)
        # Exactly 5 and not extendable on either end -> win
        if total == 5 and not (neg_extendable or pos_extendable):
            line = list(reversed(neg_coords)) + [(row, col)] + pos_coords
            return (color, line)

    return (None, None)


def board_full(board: Board) -> bool:
    for row in board:
        for v in row:
            if v == 0:
                return False
    return True


class GameState:
    def __init__(self, board_size: int = 15, human_starts: bool = True) -> None:
        self.board_size: int = board_size
        self.board: Board = [[0 for _ in range(board_size)] for _ in range(board_size)]
        self.human_color: int = 1 if human_starts else 2
        self.ai_color: int = 2 if human_starts else 1
        self.last_move: Optional[Tuple[int, int]] = None
        self.winning_line: Optional[list[tuple[int, int]]] = None
        self.winner: Optional[int] = None
        self.is_draw: bool = False
        self.moves_count: int = 0
        # Starter is always Black
        self.next_color = 1

    def reset(self, human_starts: bool = True) -> None:
        self.board = [[0 for _ in range(self.board_size)] for _ in range(self.board_size)]
        self.next_color = 1
        self.human_color = 1 if human_starts else 2
        self.ai_color = 2 if human_starts else 1
        self.last_move = None
        self.winning_line = None
        self.winner = None
        self.is_draw = False
        self.moves_count = 0

    def is_legal(self, row: int, col: int) -> bool:
        if self.winner is not None or self.is_draw:
            return False
        if row < 0 or row >= self.board_size or col < 0 or col >= self.board_size:
            return False
        return self.board[row][col] == 0

    def place_stone(self, row: int, col: int) -> bool:
        if not self.is_legal(row, col):
            return False
        color = self.next_color
        self.board[row][col] = color
        self.last_move = (row, col)
        self.moves_count += 1
        w, line = check_winner(self.board, row, col)
        if w is not None:
            self.winner = w
            self.winning_line = line or []
        elif board_full(self.board):
            self.is_draw = True
        else:
            # toggle turn
            self.next_color = 2 if self.next_color == 1 else 1
        return True

    def current_turn_color(self) -> int:
        return self.next_color

    def get_empty_intersections(self) -> list[tuple[int, int]]:
        empties: list[tuple[int, int]] = []
        for r in range(self.board_size):
            for c in range(self.board_size):
                if self.board[r][c] == 0:
                    empties.append((r, c))
        return empties

    def color_at(self, row: int, col: int) -> int:
        if row < 0 or row >= self.board_size or col < 0 or col >= self.board_size:
            return -1
        return self.board[row][col]

    def copy(self) -> "game.GameState":
        new = GameState(self.board_size, human_starts=(self.human_color == 1))
        new.board = [row[:] for row in self.board]
        new.next_color = self.next_color
        new.human_color = self.human_color
        new.ai_color = self.ai_color
        new.last_move = None if self.last_move is None else (self.last_move[0], self.last_move[1])
        new.winning_line = None if self.winning_line is None else [(r, c) for (r, c) in self.winning_line]
        new.winner = self.winner
        new.is_draw = self.is_draw
        new.moves_count = self.moves_count
        return new