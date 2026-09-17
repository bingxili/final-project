import game
import ai
import random

def test_board_full_and_checkerboard_no_win():
    size = 15
    board = [[0] * size for _ in range(size)]
    for r in range(size):
        for c in range(size):
            board[r][c] = 1 if (r + c) % 2 == 0 else 2

    assert game.board_full(board) is True

    # Using checkerboard there should be no "exactly five" line through any cell
    for pick in [(0,0), (7,7), (14,14), (0,14), (14,0)]:
        winner, line = game.check_winner(board, pick[0], pick[1])
        assert winner is None
        assert line is None

def test_exact_five_horizontal_win_detected():
    st = game.GameState(15, human_starts=True)
    # place four black in a row, then the fifth
    row = 5
    for c in range(3, 7):
        st.board[row][c] = 1
    st.next_color = 1
    assert st.place_stone(row, 7) is True
    assert st.winner == 1
    assert st.winning_line is not None and len(st.winning_line) == 5

def test_easy_ai_returns_legal_move():
    st = game.GameState(15, human_starts=True)
    st.board[7][7] = 1
    st.next_color = 2
    st.human_color = 1
    st.ai_color = 2
    move = ai.compute_best_move(st.copy(), "Easy", 0.5)
    r, c = move
    assert 0 <= r < 15 and 0 <= c < 15
    assert st.board[r][c] == 0

def test_hard_ai_wins_in_one_chooses_any_winning_endpoint():
    # AI plays black and has BBBB_ pattern with two winning ends
    st = game.GameState(15, human_starts=False)
    st.human_color = 2
    st.ai_color = 1
    row = 10
    for c in range(8, 12):
        st.board[row][c] = 1
    st.next_color = 1
    empties = [(row, 7), (row, 12)]
    chosen = ai.compute_best_move(st.copy(), "Hard", 3.0)
    assert chosen in empties