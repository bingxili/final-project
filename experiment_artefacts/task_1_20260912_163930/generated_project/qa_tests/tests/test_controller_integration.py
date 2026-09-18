import time
import threading
import copy
import unittest

import controller


def deep_copy_board(board):
    return [row[:] for row in board]


def count_color(board, color):
    return sum(cell == color for row in board for cell in row)


class FakeRoot:
    def __init__(self):
        self.destroy_called = False
        self._lock = threading.Lock()

    def after(self, delay_ms, callback, *args):
        # Schedule immediately for tests (no Tk mainloop).
        # Return an arbitrary token id.
        callback(*args)
        return object()

    def after_cancel(self, timer_id):
        # No-op for tests.
        return

    def destroy(self):
        self.destroy_called = True


class FakeView:
    def __init__(self):
        self.render_calls = []  # list of dicts: {"board":board, "last_move":lm, "winning_line":wl}
        self.status_messages = []
        self.turn_history = []  # list of tuples (is_human_turn, color)
        self.difficulty_display_history = []
        self.starter_display_history = []
        self.invalid_clicks = 0
        self.board_enabled = True

    # UI public interface methods the controller will call:

    def render_board(self, board, last_move=None, winning_line=None):
        # Store a deep copy to protect from aliasing.
        self.render_calls.append({
            "board": deep_copy_board(board),
            "last_move": None if last_move is None else (last_move[0], last_move[1]),
            "winning_line": None if winning_line is None else [(r, c) for (r, c) in winning_line],
        })

    def set_status(self, text):
        self.status_messages.append(text)

    def set_turn(self, is_human_turn, color):
        self.turn_history.append((bool(is_human_turn), int(color)))

    def set_difficulty_display(self, difficulty):
        self.difficulty_display_history.append(difficulty)

    def set_starter_display(self, starter):
        self.starter_display_history.append(starter)

    def enable_board(self):
        self.board_enabled = True

    def disable_board(self):
        self.board_enabled = False

    def flash_invalid_click(self):
        self.invalid_clicks += 1

    # Helpers for tests:

    def latest_board(self):
        if not self.render_calls:
            return None
        return self.render_calls[-1]["board"]

    def latest_last_move(self):
        if not self.render_calls:
            return None
        return self.render_calls[-1]["last_move"]

    def latest_winning_line(self):
        if not self.render_calls:
            return None
        return self.render_calls[-1]["winning_line"]


def wait_until(predicate, timeout=2.0, interval=0.005):
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if predicate():
            return True
        time.sleep(interval)
    return False


class ControllerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = FakeRoot()
        self.view = FakeView()
        self.ctrl = controller.GameController(self.root, self.view, default_difficulty='Medium', default_starter='Human')
        # Ensure a fresh game for each test
        self.ctrl.start_new_game()

    def tearDown(self):
        try:
            self.ctrl.on_quit()
        except Exception:
            # We only ensure no exception bubbles up
            pass

    def test_TC_AC1_defaults_and_start(self):
        # AC-1: Verify initial render/controls and status.
        # Expect 15x15 board and displays show Medium difficulty and Human starter, Human/Black to move.
        board = self.view.latest_board()
        self.assertIsNotNone(board, "Board was not rendered on start")
        self.assertEqual(len(board), 15, "Board rows != 15")
        self.assertTrue(all(len(row) == 15 for row in board), "Board columns != 15")

        self.assertIn('Medium', self.view.difficulty_display_history, "Difficulty display did not include 'Medium'")
        self.assertIn('Human', self.view.starter_display_history, "Starter display did not include 'Human'")

        # Last set_turn should indicate Human to move and color Black (1)
        self.assertTrue(len(self.view.turn_history) >= 1, "Turn not displayed")
        is_human_turn, color = self.view.turn_history[-1]
        self.assertTrue(is_human_turn, "Expected Human to move initially")
        self.assertEqual(color, 1, "Expected Black (1) to move initially")

    def test_TC_AC2_AC3_human_move_then_ai_medium_timing(self):
        # AC-2 and AC-3
        # Human clicks center
        t0 = time.perf_counter()
        self.ctrl.on_intersection_click(7, 7)

        # After human move, expect black stone at (7,7)
        def human_placed():
            b = self.view.latest_board()
            return b is not None and b[7][7] == 1

        self.assertTrue(wait_until(human_placed, timeout=1.0), "Human stone not placed at expected intersection")
        b_after_human = self.view.latest_board()
        self.assertEqual(b_after_human[7][7], 1, "Expected Black stone at (7,7)")

        # Turn should switch to AI (White)
        self.assertTrue(len(self.view.turn_history) >= 1)
        is_human_turn, _ = self.view.turn_history[-1]
        self.assertFalse(is_human_turn, "Turn did not switch to AI after human move")

        # Wait for AI to move (Medium should be within 1.0s)
        def ai_moved():
            b = self.view.latest_board()
            if b is None:
                return False
            lm = self.view.latest_last_move()
            if lm is None:
                return False
            r, c = lm
            return b[r][c] == 2  # last move placed by AI (White)

        self.assertTrue(wait_until(ai_moved, timeout=1.2), "AI did not make its move")

        elapsed = time.perf_counter() - t0
        self.assertLessEqual(elapsed, 1.0, f"AI (Medium) response exceeded 1.0s: {elapsed:.3f}s")

        # After AI move, it should be Human's turn again and color Black (1)
        is_human_turn, color = self.view.turn_history[-1]
        self.assertTrue(is_human_turn, "Turn did not return to Human after AI move")
        self.assertEqual(color, 1, "Expected Human/Black to move after AI")

    def test_TC_AC4_invalid_click_on_occupied(self):
        # Place at (7,7), wait AI, then attempt to place again on (7,7)
        self.ctrl.on_intersection_click(7, 7)
        # Wait until AI moved and it's Human's turn again
        def human_turn_again():
            if not self.view.turn_history:
                return False
            turn_is_human, _ = self.view.turn_history[-1]
            lm = self.view.latest_last_move()
            b = self.view.latest_board()
            return turn_is_human and lm is not None and b[lm[0]][lm[1]] != 0

        self.assertTrue(wait_until(human_turn_again, timeout=1.5), "Did not reach Human turn again")

        before_board = deep_copy_board(self.view.latest_board())
        before_turn = self.view.turn_history[-1]
        before_invalids = self.view.invalid_clicks

        self.ctrl.on_intersection_click(7, 7)  # occupied

        # Board should not change and invalid feedback should occur
        after_board = self.view.latest_board()
        self.assertEqual(before_board, after_board, "Board changed after clicking occupied intersection")
        self.assertEqual(before_turn, self.view.turn_history[-1], "Turn changed after invalid click")
        self.assertGreater(self.view.invalid_clicks, before_invalids, "Invalid click feedback not triggered")

    def test_TC_AC6_easy_timing(self):
        self.ctrl.on_difficulty_change('Easy')
        t0 = time.perf_counter()
        self.ctrl.on_intersection_click(5, 5)

        def ai_moved():
            b = self.view.latest_board()
            if b is None:
                return False
            lm = self.view.latest_last_move()
            if lm is None:
                return False
            r, c = lm
            return b[r][c] == 2  # AI (White) last moved

        self.assertTrue(wait_until(ai_moved, timeout=1.0), "AI (Easy) did not move")
        elapsed = time.perf_counter() - t0
        self.assertLessEqual(elapsed, 0.5, f"AI (Easy) response exceeded 0.5s: {elapsed:.3f}s")

    def test_TC_AC9_ai_starts(self):
        self.ctrl.on_starter_change('AI')
        self.ctrl.start_new_game()

        # Initially should indicate AI/Black to move
        self.assertTrue(len(self.view.turn_history) >= 1)
        initial_is_human, initial_color = self.view.turn_history[-1]
        self.assertFalse(initial_is_human, "Initial turn should indicate AI to move when AI starts")
        self.assertEqual(initial_color, 1, "AI should be Black when starting")

        # Wait for AI to place one Black stone
        def ai_black_moved():
            b = self.view.latest_board()
            if b is None:
                return False
            lm = self.view.latest_last_move()
            if lm is None:
                return False
            r, c = lm
            return b[r][c] == 1 and count_color(b, 1) == 1

        self.assertTrue(wait_until(ai_black_moved, timeout=1.0), "AI did not make the first move as Black")

        # After AI move, Human's turn should be displayed
        is_human_turn, color = self.view.turn_history[-1]
        self.assertTrue(is_human_turn, "After AI starts, turn should pass to Human")
        self.assertIn(color, (1, 2), "Turn color should be valid (1 or 2)")

    def test_TC_AC10_new_game_preserves_settings(self):
        self.ctrl.on_difficulty_change('Hard')
        self.ctrl.on_starter_change('Human')
        self.ctrl.start_new_game()

        # Make a move then restart
        self.ctrl.on_intersection_click(3, 3)
        # Allow possible AI move to settle
        wait_until(lambda: True, timeout=0.05)

        self.ctrl.start_new_game()

        # Board should be empty
        board = self.view.latest_board()
        self.assertIsNotNone(board)
        self.assertEqual(count_color(board, 1) + count_color(board, 2), 0, "Board not cleared on New Game")

        # Settings preserved
        self.assertTrue(self.view.difficulty_display_history, "No difficulty display updates")
        self.assertEqual(self.view.difficulty_display_history[-1], 'Hard', "Difficulty not preserved on restart")
        self.assertTrue(self.view.starter_display_history, "No starter display updates")
        self.assertEqual(self.view.starter_display_history[-1], 'Human', "Starter not preserved on restart")

        # Status should indicate starting player's turn (Human/Black)
        self.assertTrue(self.view.turn_history, "No turn status after restart")
        is_human_turn, color = self.view.turn_history[-1]
        self.assertTrue(is_human_turn, "Expected Human turn after restart with Human starter")
        self.assertEqual(color, 1, "Expected Black to move after restart with Human starter")

    def test_TC_AC11_change_difficulty_midgame(self):
        # Default Medium -> change to Easy and verify next AI move timing
        self.ctrl.on_difficulty_change('Easy')
        t0 = time.perf_counter()
        self.ctrl.on_intersection_click(4, 4)

        def ai_moved():
            b = self.view.latest_board()
            if b is None:
                return False
            lm = self.view.latest_last_move()
            if lm is None:
                return False
            r, c = lm
            return b[r][c] == 2

        self.assertTrue(wait_until(ai_moved, timeout=1.0), "AI did not move after difficulty change to Easy")
        elapsed = time.perf_counter() - t0
        self.assertLessEqual(elapsed, 0.5, f"AI (after change to Easy) response exceeded 0.5s: {elapsed:.3f}s")
        self.assertTrue(self.view.difficulty_display_history, "Difficulty display not updated")
        self.assertEqual(self.view.difficulty_display_history[-1], 'Easy', "Difficulty indicator did not reflect Easy")

    def test_TC_AC14_last_move_marker_updates(self):
        # Human move then wait AI move; verify last_move updates accordingly via render calls
        self.ctrl.on_intersection_click(6, 6)
        # Wait until human move is reflected
        self.assertTrue(wait_until(lambda: self.view.latest_board() is not None and self.view.latest_board()[6][6] == 1, timeout=1.0))

        lm_after_human = self.view.latest_last_move()
        self.assertEqual(lm_after_human, (6, 6), "last_move not set to human move")

        # Wait for AI move to occur
        self.assertTrue(wait_until(lambda: self.view.latest_last_move() is not None and self.view.latest_board()[self.view.latest_last_move()[0]][self.view.latest_last_move()[1]] == 2, timeout=1.2), "AI did not move")

        lm_after_ai = self.view.latest_last_move()
        brd = self.view.latest_board()
        self.assertIsNotNone(lm_after_ai)
        self.assertEqual(brd[lm_after_ai[0]][lm_after_ai[1]], 2, "last_move did not update to the AI's most recent stone")

    def test_TC_AC15_quit(self):
        # Should call root.destroy without raising
        self.ctrl.on_quit()
        self.assertTrue(self.root.destroy_called, "Quit did not destroy the application root")

if __name__ == '__main__':
    unittest.main()