from __future__ import annotations

import threading
import time
import tkinter

import ai
import game
import ui


DIFFICULTY_TIME_LIMITS = {
    "Easy": 0.5,
    "Medium": 1.0,
    "Hard": 3.0,
}


class GameController:
    def __init__(self, root: tkinter.Tk, view: ui.GomokuView, default_difficulty: str = 'Medium', default_starter: str = 'Human') -> None:
        self.root = root
        self.view = view
        self.difficulty: str = default_difficulty
        self.starter: str = default_starter
        self.state = game.GameState(board_size=15, human_starts=(self.starter == "Human"))
        self.ai_job_id: int = 0
        self._quitting = False

        # initialize displays
        self.view.set_difficulty_display(self.difficulty)
        self.view.set_starter_display(self.starter)
        self._update_status_turn()

    def start_new_game(self) -> None:
        # Invalidate any in-flight AI computations
        self.ai_job_id += 1

        human_starts = (self.starter == "Human")
        self.state.reset(human_starts=human_starts)
        self.view.render_board(self.state.board, self.state.last_move, self.state.winning_line)
        self._update_status_turn()
        # If AI starts, immediately schedule AI move
        if not human_starts:
            self._schedule_ai_move()
        else:
            self.view.enable_board()

    def _update_status_turn(self) -> None:
        is_human_turn = (self.state.current_turn_color() == self.state.human_color)
        color = self.state.current_turn_color()
        if self.state.winner is not None:
            winner = "Black" if self.state.winner == 1 else "White"
            who = "Human" if self.state.winner == self.state.human_color else "AI"
            self.view.set_status(f"Game Over: {who} wins ({winner}). Click New Game to play again.")
        elif self.state.is_draw:
            self.view.set_status("Game Over: Draw. Click New Game to play again.")
        else:
            who = "Human" if is_human_turn else "AI"
            colname = "Black" if color == 1 else "White"
            self.view.set_status(f"{who} to move ({colname}). Difficulty: {self.difficulty}")
        self.view.set_turn(is_human_turn, color)

    def _apply_move_and_update(self, row: int, col: int) -> None:
        if not self.state.place_stone(row, col):
            return
        self.view.render_board(self.state.board, self.state.last_move, self.state.winning_line)
        # Post-move checks
        if self.state.winner is not None or self.state.is_draw:
            self.view.disable_board()
            self._update_status_turn()
            return
        # Toggle turn status
        self._update_status_turn()

    def on_intersection_click(self, row: int, col: int) -> None:
        # Only accept clicks if it's human's turn
        if self.state.winner is not None or self.state.is_draw:
            self.view.flash_invalid_click()
            return
        if self.state.current_turn_color() != self.state.human_color:
            # not human's turn
            self.view.flash_invalid_click()
            return
        if not self.state.is_legal(row, col):
            # Avoid message flicker: rely on a consistent flash feedback
            self.view.flash_invalid_click()
            return

        self._apply_move_and_update(row, col)
        # Now AI's turn
        if self.state.current_turn_color() == self.state.ai_color and (self.state.winner is None and not self.state.is_draw):
            self._schedule_ai_move()

    def _schedule_ai_move(self) -> None:
        # Disable board during AI
        self.view.disable_board()
        self.ai_job_id += 1
        my_job = self.ai_job_id
        state_copy = self.state.copy()
        difficulty = self.difficulty
        time_limit = DIFFICULTY_TIME_LIMITS.get(difficulty, 1.0)

        def worker():
            try:
                move = ai.compute_best_move(state_copy, difficulty, time_limit)
            except Exception:
                move = None
            # small delay to ensure UI has reflected previous human move before AI applies
            # keeps UI responsive and well within time limits
            try:
                time.sleep(min(0.02, time_limit))
            except Exception:
                pass

            # marshal back to main thread
            def apply():
                if self._quitting:
                    return
                if my_job != self.ai_job_id:
                    return  # stale
                if self.state.winner is not None or self.state.is_draw:
                    return
                # Ensure still AI turn
                if self.state.current_turn_color() != self.state.ai_color:
                    return
                if move is None:
                    # fallback: pick first empty
                    empties = self.state.get_empty_intersections()
                    if not empties:
                        return
                    r, c = empties[0]
                else:
                    r, c = move
                if self.state.is_legal(r, c):
                    self._apply_move_and_update(r, c)
                # After AI move, if game not over, enable board for human
                if self.state.winner is None and not self.state.is_draw:
                    if self.state.current_turn_color() == self.state.human_color:
                        self.view.enable_board()
                    else:
                        # Rare but in case of invalid, schedule again
                        self._schedule_ai_move()
            try:
                if not self._quitting and self.root.winfo_exists():
                    self.root.after(0, apply)
            except tkinter.TclError:
                # Root may be destroyed during quit
                pass

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def on_difficulty_change(self, difficulty: str) -> None:
        if difficulty not in DIFFICULTY_TIME_LIMITS:
            difficulty = "Medium"
        self.difficulty = difficulty
        self.view.set_difficulty_display(difficulty)
        # Applies to subsequent AI moves
        self._update_status_turn()

    def on_starter_change(self, starter: str) -> None:
        if starter not in ("Human", "AI"):
            starter = "Human"
        self.starter = starter
        self.view.set_starter_display(starter)
        # No immediate change mid-game
        self._update_status_turn()

    def on_quit(self) -> None:
        self._quitting = True
        # Invalidate AI jobs to avoid late callbacks
        self.ai_job_id += 1
        try:
            self.root.destroy()
        except Exception:
            pass