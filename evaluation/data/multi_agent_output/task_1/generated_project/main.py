import tkinter
from controller import GameController
from ui import GomokuView


def main() -> None:
    root = tkinter.Tk()
    root.title("Gomoku - Five in a Row")
    # Reasonable initial size; Canvas handles drawing
    root.geometry("900x700")
    view = GomokuView(
        root,
        board_size=15,
    )
    controller = GameController(root, view, default_difficulty='Medium', default_starter='Human')

    # Wire view callbacks after controller creation
    view.on_intersection_click = controller.on_intersection_click
    view.on_new_game = controller.start_new_game
    view.on_quit = controller.on_quit
    view.on_difficulty_change = controller.on_difficulty_change
    view.on_starter_change = controller.on_starter_change

    controller.start_new_game()

    # Clean quit on window close
    def on_close():
        controller.on_quit()
    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


if __name__ == "__main__":
    main()