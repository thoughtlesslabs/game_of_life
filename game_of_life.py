import os
import sys
import time
import signal
import random
from shutil import get_terminal_size

class GameOfLife:
    def __init__(self, initial_pattern='glider'):
        self.running = True
        self.generation = 0
        self.population = 0
        self.initial_pattern = initial_pattern
        signal.signal(signal.SIGINT, self.handle_interrupt)
        self.reset_board(self.initial_pattern)

    def handle_interrupt(self, signum, frame):
        self.running = False
        print("\nGame stopped.")
        sys.exit(0)

    def reset_board(self, pattern='random'):
        cols, rows = get_terminal_size()
        self.width = cols # Use full width
        self.height = rows - 1 # Leave one row for status
        self.board = [[0 for _ in range(self.width)] for _ in range(self.height)]
        self.generation = 0
        self.population = 0

        if pattern == 'random':
            self.board = [[random.choice([0, 1]) for _ in range(self.width)]
                         for _ in range(self.height)]
        elif pattern == 'glider':
            self._place_glider(1, 1) # Place glider at top-left corner
        elif pattern == 'block':
            self._place_block(1, 1)
        elif pattern == 'blinker':
            self._place_blinker(1, 1)
        elif pattern == 'lwss':
            self._place_lwss(1, 1) # Lightweight Spaceship
        # Add more patterns here if needed (e.g., 'block', 'blinker')

        # Calculate initial population
        self._update_population()

    def _place_glider(self, x, y):
        """Places a glider pattern with top-left at (x, y)"""
        glider = [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)]
        for dx, dy in glider:
            nx, ny = (x + dx) % self.width, (y + dy) % self.height
            if 0 <= ny < self.height and 0 <= nx < self.width:
                self.board[ny][nx] = 1

    def _place_block(self, x, y):
        """Places a block pattern with top-left at (x, y)"""
        block = [(0, 0), (1, 0), (0, 1), (1, 1)]
        for dx, dy in block:
            nx, ny = (x + dx) % self.width, (y + dy) % self.height
            if 0 <= ny < self.height and 0 <= nx < self.width:
                self.board[ny][nx] = 1

    def _place_blinker(self, x, y):
        """Places a blinker pattern (vertical phase) with top-left at (x, y)"""
        blinker = [(0, 1), (1, 1), (2, 1)] # Centered in a 3x3 box starting at x,y
        # Adjust x,y to be the center of the 3x3 for simpler relative coords
        center_x, center_y = x + 1, y + 1
        blinker_rel = [(0, -1), (0, 0), (0, 1)] # Vertical blinker relative to center
        for dx, dy in blinker_rel:
            nx, ny = (center_x + dx) % self.width, (center_y + dy) % self.height
            if 0 <= ny < self.height and 0 <= nx < self.width:
                self.board[ny][nx] = 1

    def _place_lwss(self, x, y):
        """Places a Lightweight Spaceship (LWSS) pattern heading right, with top-left at (x, y)"""
        # Coords relative to top-left (x,y) of a 5x4 bounding box
        lwss = [
            (1, 0), (4, 0),
            (0, 1),
            (0, 2), (4, 2),
            (0, 3), (1, 3), (2, 3), (3, 3)
        ]
        for dx, dy in lwss:
            nx, ny = (x + dx) % self.width, (y + dy) % self.height
            if 0 <= ny < self.height and 0 <= nx < self.width:
                self.board[ny][nx] = 1

    def _update_population(self):
        """Calculates the number of live cells."""
        self.population = sum(sum(row) for row in self.board)

    def get_neighbors(self, x, y):
        count = 0
        for i in range(-1, 2):
            for j in range(-1, 2):
                if i == 0 and j == 0:
                    continue
                nx, ny = (x + i) % self.width, (y + j) % self.height
                count += self.board[ny][nx]
        return count

    def next_generation(self):
        new_board = [[0 for x in range(self.width)]
                    for y in range(self.height)]
        live_cells_next = 0
        for y in range(self.height):
            for x in range(self.width):
                neighbors = self.get_neighbors(x, y)
                if self.board[y][x]:
                    if neighbors in [2, 3]:
                        new_board[y][x] = 1
                        live_cells_next += 1
                    # else: cell dies, new_board[y][x] remains 0
                else:
                    if neighbors == 3:
                        new_board[y][x] = 1
                        live_cells_next += 1
                    # else: cell stays dead, new_board[y][x] remains 0

        self.board = new_board
        self.generation += 1
        self.population = live_cells_next # Update population more efficiently

    def draw(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        output = []
        for row in self.board:
            output.append(''.join('o' if cell else ' ' for cell in row)) # Use 'o' for live cells

        # Prepare status line
        status = f"Generation: {self.generation} | Population: {self.population}"
        # Pad status line to full width to overwrite previous longer lines
        status_line = status.ljust(self.width)

        # Print board and status line
        print("\n".join(output))
        print(status_line, end='', flush=True) # Use end='' and flush

    def run(self):
        while self.running:
            current_cols, current_rows = get_terminal_size()
            # Check if size changed, use full width now
            if (current_cols != self.width or
                current_rows - 1 != self.height):
                # Reset with the initial pattern on resize
                self.reset_board(self.initial_pattern)

            self.draw()
            self.next_generation()
            time.sleep(0.1) # Keep the original sleep time

if __name__ == "__main__":
    # Can add argument parsing here later to select pattern
    # Choose initial pattern: 'random', 'glider', 'block', 'blinker', 'lwss'
    chosen_pattern = 'lwss' # Example: Start with LWSS
    game = GameOfLife(initial_pattern=chosen_pattern)
    game.run()
