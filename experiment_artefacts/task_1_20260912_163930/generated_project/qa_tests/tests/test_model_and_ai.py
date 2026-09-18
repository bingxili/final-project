import time
import unittest

import game
import ai


class ModelAndAiTests(unittest.TestCase):
    def test_TC_AC7_medium_blocks_immediate_win_in_one(self):
        # Human starts as Black (1), AI is White (2)
        state = game.GameState(board_size=15, human_starts=True)
        # Build a row where human (1) has four consecutive stones with exactly one adjacent empty cell,
        # and the other side is blocked by AI (2). It is AI's turn.
        # Sequence:
        # 1:(7,5) 2:(0,0) 1:(7,6) 2:(0,1) 1:(7,7) 2:(7,4) 1:(7,8)
        moves = [
            (7, 5), (0, 0),
            (7, 6), (0, 1),
            (7, 7), (7, 4),
            (7, 8)
        ]
        for r, c in moves:
            ok = state.place_stone(r, c)
            self.assertTrue(ok, f"Failed to place stone at {(r,c)} during setup")

        # Now it's AI's (White/2) turn. The only blocking move is at (7,9).
        r, c = ai.compute_best_move(state, 'Medium', time_limit=1.0)
        self.assertEqual((r, c), (7, 9), f"Medium did not block immediate win; chose {(r,c)} instead of (7,9)")

    def test_TC_AC8_hard_takes_immediate_winning_move(self):
        # Human starts as Black (1), AI is White (2). Make it AI's turn with AI having four-in-a-row.
        state = game.GameState(board_size=15, human_starts=True)
        # Build AI's four at (7,5),(7,6),(7,7),(7,8) with (7,9) empty and it's AI's turn.
        # Sequence placing alternates colors, ending with AI to move:
        # 1:(0,0) 2:(7,5) 1:(0,1) 2:(7,6) 1:(0,2) 2:(7,7) 1:(0,3) 2:(7,8) 1:(0,4)
        moves = [
            (0, 0), (7, 5),
            (0, 1), (7, 6),
            (0, 2), (7, 7),
            (0, 3), (7, 8),
            (0, 4)
        ]
        for r, c in moves:
            ok = state.place_stone(r, c)
            self.assertTrue(ok, f"Failed to place stone at {(r,c)} during setup")

        # It's now AI's (White/2) turn. Winning move expected at (7,9).
        r, c = ai.compute_best_move(state, 'Hard', time_limit=3.0)
        self.assertEqual((r, c), (7, 9), f"Hard did not take immediate winning move; chose {(r,c)} instead of (7,9)")

    def test_TC_AC12_win_detection_check_winner(self):
        # Make a simple horizontal five for Black at row 10, cols 3..7
        size = 15
        board = [[0] * size for _ in range(size)]
        coords = [(10, c) for c in range(3, 8)]
        for (r, c) in coords:
            board[r][c] = 1  # Black

        # The last move is the final stone placed; check_winner should report Black and the winning line
        winner, line = game.check_winner(board, 10, 7)
        self.assertEqual(winner, 1, "Winner should be Black (1)")
        self.assertIsNotNone(line, "Winning line should be returned")
        self.assertEqual(set(line), set(coords), "Winning line does not match the five-in-a-row")

    def test_TC_AC13_draw_detection_board_full(self):
        # Fill a checkerboard pattern to avoid any five-in-a-row; board should be full.
        size = 15
        board = [[0] * size for _ in range(size)]
        for r in range(size):
            for c in range(size):
                board[r][c] = 1 if (r + c) % 2 == 0 else 2

        self.assertTrue(game.board_full(board), "board_full should return True on a completely filled board")

        # Pick the last placed location and verify no win is detected for that last stone
        # Choose an arbitrary cell; for safety, choose (14,14) which is Black in checkerboard
        winner, line = game.check_winner(board, 14, 14)
        self.assertIsNone(winner, "No winner should be detected on checkerboard pattern")
        self.assertIsNone(line, "Winning line should be None when there is no winner")

    def test_TC_AC16_ai_compute_timing_across_difficulties(self):
        # Construct a small mid-game state without immediate wins to time compute_best_move
        state = game.GameState(board_size=15, human_starts=True)
        setup_moves = [
            (7, 7), (7, 8),
            (6, 6), (8, 8),
            (6, 7), (8, 7),
            (7, 6)
        ]
        for r, c in setup_moves:
            ok = state.place_stone(r, c)
            self.assertTrue(ok, f"Failed to place stone at {(r,c)} during setup")

        # Ensure it's AI's turn when timing Medium and Hard (alternate if needed)
        # If next_color is 1 (Human), place a harmless Human move to pass turn to AI.
        # We cannot access next_color directly by contract; instead, try a harmless placement and revert if illegal.
        # Safer approach: time on a copied state where it's AI's turn after placing one more Human stone.
        base_state = state.copy()
        extra_move_done = base_state.place_stone(0, 0)  # Human move; OK to call as part of setup
        self.assertTrue(extra_move_done, "Failed to adjust turn to AI for timing tests")

        # Easy timing
        t0 = time.perf_counter()
        move_e = ai.compute_best_move(base_state, 'Easy', time_limit=0.5)
        dt_e = time.perf_counter() - t0
        self.assertIsInstance(move_e, tuple)
        self.assertLessEqual(dt_e, 0.5, f"Easy compute exceeded 0.5s: {dt_e:.3f}s")

        # Medium timing
        t0 = time.perf_counter()
        move_m = ai.compute_best_move(base_state, 'Medium', time_limit=1.0)
        dt_m = time.perf_counter() - t0
        self.assertIsInstance(move_m, tuple)
        self.assertLessEqual(dt_m, 1.0, f"Medium compute exceeded 1.0s: {dt_m:.3f}s")

        # Hard timing
        t0 = time.perf_counter()
        move_h = ai.compute_best_move(base_state, 'Hard', time_limit=3.0)
        dt_h = time.perf_counter() - t0
        self.assertIsInstance(move_h, tuple)
        self.assertLessEqual(dt_h, 3.0, f"Hard compute exceeded 3.0s: {dt_h:.3f}s")

    # Note: AC-5 (click snapping/ignoring outside grid) involves pixel-level UI interactions.
    # There is no public interface in ui.GomokuView to inject raw click coordinates without running a Tk event loop.
    # Thus, this behavior cannot be exercised directly in these black-box tests without starting the GUI.


if __name__ == '__main__':
    unittest.main()