from __future__ import annotations

import random
from typing import Tuple

import game


def _simulate_move_wins(board: list[list[int]], row: int, col: int, color: int) -> bool:
    if board[row][col] != 0:
        return False
    board[row][col] = color
    w, _ = game.check_winner(board, row, col)
    board[row][col] = 0
    return w is not None


def _center_bias_score(size: int, row: int, col: int) -> float:
    center = (size - 1) / 2.0
    dr = abs(row - center)
    dc = abs(col - center)
    # closer to center => higher score
    return -(dr * dr + dc * dc)


def _adjacency_score(board: list[list[int]], row: int, col: int) -> int:
    # count neighboring stones within Chebyshev distance 1 and 2 with higher weight near
    total = 0
    size = len(board)
    for r in range(row - 2, row + 3):
        for c in range(col - 2, col + 3):
            if r == row and c == col:
                continue
            if 0 <= r < size and 0 <= c < size and board[r][c] != 0:
                dist = max(abs(r - row), abs(c - col))
                if dist == 1:
                    total += 3
                elif dist == 2:
                    total += 1
    return total


def compute_best_move(state: game.GameState, difficulty: str, time_limit: float) -> tuple[int, int]:
    """
    Computes a legal move for the AI given the current state and difficulty.
    Notes:
    - This function is designed to run quickly on up to 225 empties and typically does
      not need to consult time_limit; if future heuristics get heavier, this can be
      used to bound computation.
    - Precondition: there exists at least one legal empty intersection.
    """
    size = state.board_size
    ai_color = state.ai_color
    human_color = state.human_color
    empties = state.get_empty_intersections()
    if not empties:
        raise RuntimeError("No legal moves available")

    # Prepare a center-biased ordering of empties to produce more natural choices
    empties_center_first = sorted(empties, key=lambda rc: _center_bias_score(size, rc[0], rc[1]), reverse=True)

    # Hard: take immediate winning move (search across all and pick center-biased best)
    if difficulty == "Hard":
        winning_moves = [(r, c) for (r, c) in empties if _simulate_move_wins(state.board, r, c, ai_color)]
        if winning_moves:
            winning_moves.sort(key=lambda rc: _center_bias_score(size, rc[0], rc[1]), reverse=True)
            # break ties randomly among best center score to add slight variety
            best_score = _center_bias_score(size, winning_moves[0][0], winning_moves[0][1])
            top = [mv for mv in winning_moves if _center_bias_score(size, mv[0], mv[1]) == best_score]
            return random.choice(top)

    # Medium/Hard: block opponent immediate win-in-one (choose among candidates)
    if difficulty in ("Medium", "Hard"):
        opponent_winning_moves = [(r, c) for (r, c) in empties if _simulate_move_wins(state.board, r, c, human_color)]
        if opponent_winning_moves:
            # Prefer center-biased among blocking moves
            opponent_winning_moves.sort(key=lambda rc: _center_bias_score(size, rc[0], rc[1]), reverse=True)
            # Some variety: pick randomly among the top-scoring blocking moves
            best_score = _center_bias_score(size, opponent_winning_moves[0][0], opponent_winning_moves[0][1])
            top = [mv for mv in opponent_winning_moves if _center_bias_score(size, mv[0], mv[1]) == best_score]
            return random.choice(top)

    # Easy: quick center-biased random
    if difficulty == "Easy":
        top = max(1, min(10, len(empties_center_first) // 4 or 1))
        choice = random.choice(empties_center_first[:top])
        return choice

    # Medium/Hard fallback: simple heuristic (adjacency + center)
    best_score = float("-inf")
    best_moves: list[tuple[int, int]] = []
    for (r, c) in empties:
        score = 0.0
        score += _adjacency_score(state.board, r, c) * 1.0
        score += _center_bias_score(size, r, c) * 0.1
        # slight preference to be adjacent to last move
        if state.last_move is not None:
            lr, lc = state.last_move
            if max(abs(lr - r), abs(lc - c)) == 1:
                score += 0.5
        if score > best_score:
            best_score = score
            best_moves = [(r, c)]
        elif score == best_score:
            best_moves.append((r, c))
    if not best_moves:
        return random.choice(empties)
    return random.choice(best_moves)