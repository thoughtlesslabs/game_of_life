import random
import os
import asyncio
import time

# ANSI escape codes (no longer used directly in rendering string)
# CLEAR_SCREEN = "\033[H\033[J"

# --- Constants ---
# ANSI color codes
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"

# Colors for different cell types (using more stable colors)
COLOR_DEAD = "\033[38;5;236m"  # Darker gray for less contrast
COLOR_LIVE = "\033[38;5;40m"   # Softer green
COLOR_PLAYER = "\033[38;5;220m"  # Softer yellow
COLOR_OTHER = "\033[38;5;208m"  # Softer orange

# Rendering characters using Braille patterns with colors
# Using more stable patterns that don't cause flickering
RENDER_DEAD = f"{COLOR_DEAD}⠄{COLOR_RESET}"  # Light dot pattern
RENDER_LIVE = f"{COLOR_LIVE}⠿{COLOR_RESET}"  # Full pattern
RENDER_PLAYER = f"{COLOR_PLAYER}⣿{COLOR_RESET}"  # Full pattern
RENDER_OTHER_PLAYER = f"{COLOR_OTHER}⣾{COLOR_RESET}"  # Slightly different pattern

# Screen clearing codes
CLEAR_SCREEN = "\033[2J\033[H"  # Clear screen and move cursor to top
CLEAR_LINE = "\033[K"  # Clear current line

# Internal grid states
INTERNAL_DEAD = 0
INTERNAL_LIVE = -1 # Use negative to distinguish from player IDs >= 1

# --- Player Spawn Pattern (Glider) ---
# Standard Glider shape relative coordinates
# . @ .
# . . @
# @ @ @
PLAYER_SPAWN_PATTERN = [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)] 
PATTERN_WIDTH = 3 # Max width of glider pattern
PATTERN_HEIGHT = 3 # Max height of glider pattern
# --- End Player Spawn Pattern ---

# --- Standard Patterns for Seeding ---
STANDARD_PATTERNS = {
    # Glider is now player spawn, maybe use others?
    # "glider": [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)], 
    "block": [(0, 0), (0, 1), (1, 0), (1, 1)],
    "blinker_h": [(0,0), (0,1), (0,2)], # Horizontal Blinker (period 2 oscillator)
    "lwss": [(0,1), (0,4), (1,0), (2,0), (2,4), (3,0), (3,1), (3,2), (3,3)] # LightWeight SpaceShip
}
STANDARD_PATTERN_DIMS = {
    # "glider": (3, 3),
    "block": (2, 2),
    "blinker_h": (1, 3),
    "lwss": (4, 5)
}
# --- End Standard Patterns ---

# --- Game Constants ---
RESPAWN_COOLDOWN = 15 # Seconds
# --- End Game Constants ---

class GameOfLife:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        # Initialize grid with internal dead state
        self.grid = [[INTERNAL_DEAD for _ in range(width)] for _ in range(height)]
        # Player state: player_id -> {'pos': (r, c), 'last_respawn_time': timestamp, 'respawn_count': int}
        self.players = {}
        self.generation_count = 0
        # Place specific patterns instead of purely random seeding
        # Use new standard patterns, removed glider as it's player spawn
        self._seed_patterns(num_blocks=5, num_blinkers=5, num_lwss=3) 

    def _is_valid(self, r, c):
        """Check if coordinates are within grid bounds."""
        return 0 <= r < self.height and 0 <= c < self.width

    def _is_area_clear(self, start_r, start_c, pattern_coords):
        """Checks if the area for a pattern is empty (INTERNAL_DEAD)."""
        for dr, dc in pattern_coords:
            r, c = (start_r + dr) % self.height, (start_c + dc) % self.width
            if not self._is_valid(r, c) or self.grid[r][c] != INTERNAL_DEAD:
                return False
        return True

    def _place_pattern(self, start_r, start_c, pattern_coords, state=INTERNAL_LIVE):
        """Places a pattern using the specified state, assuming area is clear."""
        for dr, dc in pattern_coords:
            r, c = (start_r + dr) % self.height, (start_c + dc) % self.width
            if self._is_valid(r, c):
                self.grid[r][c] = state

    def _seed_patterns(self, num_blocks=3, num_blinkers=3, num_lwss=2):
        """Seeds the board with a specific number of standard patterns."""
        # Use the STANDARD_PATTERNS definitions
        patterns_to_seed = [
            ("block", num_blocks),
            ("blinker_h", num_blinkers),
            ("lwss", num_lwss)
        ]

        placements = [] # Keep track of placed pattern top-left corners and types
        max_attempts_per_pattern = 100

        for pattern_name, num_to_place in patterns_to_seed:
            if pattern_name not in STANDARD_PATTERNS:
                 print(f"WARN: Pattern '{pattern_name}' not defined in STANDARD_PATTERNS. Skipping.")
                 continue
            
            pattern_coords = STANDARD_PATTERNS[pattern_name]
            p_height, p_width = STANDARD_PATTERN_DIMS[pattern_name]
            
            placed_count = 0
            for _ in range(num_to_place):
                attempt = 0
                placed_this_one = False
                while attempt < max_attempts_per_pattern and not placed_this_one:
                    start_r = random.randint(0, self.height - p_height)
                    start_c = random.randint(0, self.width - p_width)
                    
                    # Basic overlap check
                    too_close = False
                    proximity = max(p_width, p_height) + 2 # Minimum distance between patterns
                    for pr, pc, _ in placements:
                        if abs(start_r - pr) < proximity and abs(start_c - pc) < proximity:
                            too_close = True
                            break
                    if too_close:
                        attempt += 1
                        continue
                    
                    if self._is_area_clear(start_r, start_c, pattern_coords):
                        self._place_pattern(start_r, start_c, pattern_coords, INTERNAL_LIVE)
                        placements.append((start_r, start_c, pattern_name))
                        placed_this_one = True
                        placed_count += 1
                    attempt += 1
            print(f"DEBUG: Placed {placed_count}/{num_to_place} requested '{pattern_name}' patterns.")

        if placements:
             print(f"DEBUG: Seeded total {len(placements)} patterns.")
        else:
             print(f"WARN: Failed to seed any patterns.")

    def _get_neighbors_state(self, r, c):
        """Counts live neighbors and identifies unique player IDs among them."""
        live_neighbor_count = 0
        neighbor_player_ids = set()

        for i in range(-1, 2):
            for j in range(-1, 2):
                if i == 0 and j == 0:
                    continue # Skip the cell itself

                # Calculate neighbor coordinates with wrapping
                nr, nc = (r + i) % self.height, (c + j) % self.width

                neighbor_state = self.grid[nr][nc]
                if neighbor_state == INTERNAL_LIVE: # Standard live cell
                    live_neighbor_count += 1
                elif neighbor_state > 0: # Player cell (ID > 0)
                    live_neighbor_count += 1
                    neighbor_player_ids.add(neighbor_state)

        return live_neighbor_count, neighbor_player_ids

    def next_generation(self):
        """Calculates the next state of the grid based on modified Conway's rules with player influence."""
        new_grid = [[self.grid[r][c] for c in range(self.width)] for r in range(self.height)]

        for r in range(self.height):
            for c in range(self.width):
                current_state = self.grid[r][c]
                live_neighbors_count, neighbor_player_ids = self._get_neighbors_state(r, c)
                # Determine next state based purely on Conway rules
                # Treat player cells (value > 0) as live for rule application
                should_be_alive = False
                is_currently_live = (current_state == INTERNAL_LIVE or current_state > 0)
                
                if is_currently_live:
                    # Standard live cell survival
                    if 2 <= live_neighbors_count <= 3:
                        should_be_alive = True
                else: # Currently INTERNAL_DEAD
                    # Birth rule
                    if live_neighbors_count == 3:
                        should_be_alive = True

                # Apply the state change or influence
                if should_be_alive:
                    # Check for single player influence
                    if len(neighbor_player_ids) == 1 and live_neighbors_count > 0:
                        influencing_pid = list(neighbor_player_ids)[0]
                        # Check if the influencing player is different from the current cell owner (if any)
                        # This prevents a player cell from being influenced *by itself* into INTERNAL_LIVE
                        if influencing_pid != current_state: 
                           new_grid[r][c] = influencing_pid # Cell becomes player-controlled
                        # Check added for clarity: a surviving player cell not influenced stays as its ID
                        elif current_state > 0 and influencing_pid != current_state:
                            # This case should be rare/impossible if influence logic is correct
                            # but ensures a player cell doesn't turn into INTERNAL_LIVE
                            # if it survives but isn't influenced by someone else.
                            pass # Remains its current player ID (already in new_grid)
                    else:
                        # Becomes/remains standard live cell if no single influence
                        # or if it's a player cell with mixed/no player neighbors
                        # Important: Preserve existing player cell if it wasn't overwritten by influence
                        if not is_currently_live:
                             new_grid[r][c] = INTERNAL_LIVE
                else:
                    # Cell should be dead
                    new_grid[r][c] = INTERNAL_DEAD

        self.grid = new_grid
        self.generation_count += 1 # Increment generation count

    def add_player(self, player_id, inject_disruption=False):
        """Adds a player pattern, initializes their stats, and optionally injects disruption."""
        # REMOVED: Check for existing player - respawn handles removal first.
        # if player_id in self.players:
        #      print(f"DEBUG: add_player called for existing player {player_id}")
        #      return True

        attempts = 0
        max_attempts = (self.width * self.height) // (PATTERN_WIDTH * PATTERN_HEIGHT)
        max_attempts = max(100, max_attempts) # Ensure reasonable attempts
        placed_at = None

        while attempts < max_attempts and placed_at is None:
            # Choose a random top-left corner for the pattern
            # Ensure pattern fits within bounds (subtract pattern dims)
            start_r = random.randint(0, self.height - PATTERN_HEIGHT)
            start_c = random.randint(0, self.width - PATTERN_WIDTH)

            # Check if the area is clear
            # Uses PLAYER_SPAWN_PATTERN (now glider)
            can_place = self._is_area_clear(start_r, start_c, PLAYER_SPAWN_PATTERN)
            
            if can_place:
                # Place the pattern using player_id
                # Uses PLAYER_SPAWN_PATTERN (now glider)
                self._place_pattern(start_r, start_c, PLAYER_SPAWN_PATTERN, player_id)
                # Initialize player stats
                current_time = asyncio.get_event_loop().time() if asyncio.get_running_loop() else time.time() # Use time if no loop
                self.players[player_id] = {
                     'pos': (start_r, start_c), 
                     'last_respawn_time': current_time - RESPAWN_COOLDOWN, # Allow immediate respawn first time
                     'respawn_count': 0
                 }
                placed_at = (start_r, start_c)
                # print(f"DEBUG: Added player {player_id} pattern at {placed_at}")

            attempts += 1

        if placed_at:
            # --- Inject Disruption if Requested ---
            if inject_disruption:
                start_r, start_c = placed_at
                disruption_radius = 3 # How far around the player to add cells
                num_disrupt_cells = 5 # How many extra live cells to add
                disrupted_count = 0
                disrupt_attempts = 0
                max_disrupt_attempts = 20
                print(f"DEBUG: Injecting disruption around player {player_id} at ({start_r}, {start_c})")
                while disrupted_count < num_disrupt_cells and disrupt_attempts < max_disrupt_attempts:
                     # Pick random offset within radius, avoiding player pattern itself
                     offset_r = random.randint(-disruption_radius, disruption_radius)
                     offset_c = random.randint(-disruption_radius, disruption_radius)
                     # Simple check to avoid placing directly on the glider spawn footprint
                     # (This check is approximate, might still overlap glider path)
                     is_on_pattern = False
                     for dr, dc in PLAYER_SPAWN_PATTERN:
                         if offset_r == dr and offset_c == dc:
                             is_on_pattern = True
                             break
                     if is_on_pattern:
                         disrupt_attempts += 1
                         continue

                     r, c = (start_r + offset_r) % self.height, (start_c + offset_c) % self.width
                     if self._is_valid(r, c) and self.grid[r][c] == INTERNAL_DEAD:
                         self.grid[r][c] = INTERNAL_LIVE
                         disrupted_count += 1
                         # print(f"DEBUG: Added disruption cell at ({r}, {c})")
                     disrupt_attempts += 1
                if disrupted_count > 0:
                     print(f"DEBUG: Added {disrupted_count} disruption cells near player {player_id}.")
            # --- End Disruption Injection ---
            return True # Successfully placed player
        else:
             print(f"WARN: Could not find empty spot for player {player_id} pattern after {max_attempts} attempts.")
             return False # Failed to add player

    def remove_player(self, player_id):
        """Removes a player pattern and their data from the grid."""
        if player_id in self.players:
            # Retrieve position before deleting (still useful for debug prints)
            player_data = self.players.get(player_id)
            # start_r, start_c = (-1, -1) # Initialize in case pos is missing
            # if player_data and 'pos' in player_data:
            #      start_r, start_c = player_data['pos']
            # else:
            #      print(f"WARN: Player {player_id} data missing position during removal.")

            # Clear ALL cells owned by this player_id across the grid
            removed_count = 0
            for r in range(self.height):
                for c in range(self.width):
                    if self.grid[r][c] == player_id:
                        self.grid[r][c] = INTERNAL_DEAD
                        removed_count += 1
            
            # if removed_count > 0:
            #    print(f"DEBUG: Cleared {removed_count} cells for player {player_id}.")
            # elif start_r != -1: # Only warn if we had a position but found no cells
            #    print(f"DEBUG: No grid cells found for player {player_id} during removal (may have died out).")

            # Remove player entry completely
            del self.players[player_id]
            # print(f"DEBUG: Removed player {player_id} data.")
        # else: Player not found in dict, nothing to remove from grid or dict.
        #    print(f"DEBUG: remove_player called for player_id {player_id} not in self.players dict.")

    def respawn_player(self, player_id, is_god_mode=False):
        """Attempts to respawn a player, respecting cooldown.
        Args:
            player_id: The ID of the player to respawn
            is_god_mode: If True, respawns the entire board. If False, only respawns the player.
        Returns: (success: bool, message: str)
        """
        # Note: Cooldown check is now primarily done in server.py before calling this
        # But keep a basic check here for safety / direct calls
        if player_id not in self.players:
            print(f"WARN: respawn_player called for player {player_id} not in self.players dict.")
            return (False, "Player state not found. Cannot respawn.")

        player_data = self.players[player_id]
        current_time = asyncio.get_event_loop().time() if asyncio.get_running_loop() else time.time()
        last_respawn = player_data.get('last_respawn_time', 0)
        time_since_respawn = current_time - last_respawn

        if time_since_respawn < RESPAWN_COOLDOWN and not is_god_mode:
            remaining = RESPAWN_COOLDOWN - time_since_respawn
            return (False, f"Respawn cooldown: {remaining:.1f}s left.")

        print(f"DEBUG: Respawning player {player_id}...")
        old_respawn_count = player_data.get('respawn_count', 0)

        if is_god_mode:
            # God mode: Reset entire board
            # 1. Clear all cells
            for r in range(self.height):
                for c in range(self.width):
                    self.grid[r][c] = INTERNAL_DEAD
            
            # 2. Reset generation count
            self.generation_count = 0
            
            # 3. Calculate available space for players
            total_cells = self.width * self.height
            num_players = len(self.players)
            # Reserve some space for patterns (about 20% of board)
            reserved_space = total_cells // 5
            available_space = total_cells - reserved_space
            
            # If we don't have enough space for all players, reduce pattern count
            if num_players > available_space // (PATTERN_WIDTH * PATTERN_HEIGHT):
                print(f"WARN: High player count ({num_players}), reducing pattern count")
                self._seed_patterns(num_blocks=2, num_blinkers=2, num_lwss=1)
            else:
                self._seed_patterns(num_blocks=5, num_blinkers=5, num_lwss=3)
            
            # 4. Add all players back with increased max attempts
            failed_players = []
            for pid in list(self.players.keys()):
                if pid in self.players:
                    # Increase max attempts for high player count
                    success = self.add_player(pid, inject_disruption=False)
                    if not success:
                        failed_players.append(pid)
            
            if failed_players:
                print(f"WARN: Failed to respawn {len(failed_players)} players in god mode restart")
                return (False, f"Failed to respawn {len(failed_players)} players. Try again.")
            
            return (True, "Game board reset and all players respawned!")
        else:
            # Regular respawn: Only remove player cells
            # 1. Remove only the player's cells (don't remove player data)
            removed_count = 0
            for r in range(self.height):
                for c in range(self.width):
                    if self.grid[r][c] == player_id:
                        self.grid[r][c] = INTERNAL_DEAD
                        removed_count += 1
            
            # 2. Add player back with moving trait
            success = self.add_player(player_id, inject_disruption=False)

            if success:
                # 3. Update stats for the newly added player entry
                if player_id in self.players:
                    self.players[player_id]['last_respawn_time'] = current_time
                    self.players[player_id]['respawn_count'] = old_respawn_count + 1
                    # Add moving trait
                    self.players[player_id]['moving'] = True
                    self.players[player_id]['move_direction'] = (0, 1)  # Start moving right
                    print(f"DEBUG: Player {player_id} respawned with moving trait. Count: {self.players[player_id]['respawn_count']}")
                    return (True, "Respawn successful!")
                else:
                    print(f"ERROR: Player {player_id} added successfully but not found in dict after respawn?! ")
                    return (False, "Respawn error (internal state inconsistency).")
            else:
                print(f"WARN: Failed to find spot for player {player_id} during respawn.")
                return (False, "Respawn failed: Could not find empty space.")

    def get_live_cell_count(self):
        """Counts the total number of live cells (standard and player-owned)."""
        count = 0
        for r in range(self.height):
            for c in range(self.width):
                if self.grid[r][c] != INTERNAL_DEAD:
                    count += 1
        return count

    def get_render_string(self, requesting_player_id, player_state):
        """Generates the game board render string with player-specific view using Braille patterns."""
        # Get the player's position if they exist
        player_pos = self.players.get(requesting_player_id, {}).get('pos')
        if not player_pos:
            return "Error: Player not found in game state."

        # Get terminal size for responsive viewport
        try:
            term_cols, term_rows = os.get_terminal_size()
            # Use 80% of terminal width and 60% of terminal height
            # Since each Braille character represents 2x4 cells, we can show more
            view_width = int(term_cols * 0.8 * 4)  # 4x more cells horizontally
            view_height = int(term_rows * 0.6 * 2)  # 2x more cells vertically
            # Ensure minimum size
            view_width = max(240, view_width)  # Increased minimum width
            view_height = max(60, view_height)  # Increased minimum height
        except OSError:
            # Fallback to default sizes if terminal size detection fails
            view_width = 320  # Increased default width
            view_height = 80  # Increased default height

        center_r, center_c = player_pos

        # Calculate viewport boundaries with wrapping
        start_r = (center_r - view_height // 2) % self.height
        start_c = (center_c - view_width // 2) % self.width

        # Build the viewport using Braille patterns
        viewport = []
        for i in range(0, view_height, 2):  # Step by 2 for Braille height
            row = []
            for j in range(0, view_width, 4):  # Step by 4 for Braille width
                # Calculate the 8 cells that make up this Braille pattern
                cells = []
                for dr in range(2):
                    for dc in range(4):
                        r = (start_r + i + dr) % self.height
                        c = (start_c + j + dc) % self.width
                        cell = self.grid[r][c]
                        cells.append(cell)
                
                # Convert the 8 cells into a Braille pattern with smoother transitions
                if all(c == INTERNAL_DEAD for c in cells):
                    row.append(RENDER_DEAD)
                elif all(c == requesting_player_id for c in cells):
                    row.append(RENDER_PLAYER)
                elif all(c == INTERNAL_LIVE for c in cells):
                    row.append(RENDER_LIVE)
                else:
                    # If mixed, use a pattern based on majority with smoother transitions
                    player_cells = sum(1 for c in cells if c == requesting_player_id)
                    live_cells = sum(1 for c in cells if c == INTERNAL_LIVE)
                    other_player_cells = sum(1 for c in cells if c > 0 and c != requesting_player_id)
                    
                    if player_cells >= 3:  # Lowered threshold for smoother transitions
                        row.append(RENDER_PLAYER)
                    elif live_cells >= 3:
                        row.append(RENDER_LIVE)
                    elif other_player_cells >= 3:
                        row.append(RENDER_OTHER_PLAYER)
                    else:
                        row.append(RENDER_DEAD)
            
            viewport.append(''.join(row))

        # Build the status line with colored legend
        player_data = self.players.get(requesting_player_id, {})
        respawn_count = player_data.get('respawn_count', 0)
        last_respawn = player_data.get('last_respawn_time', 0)
        current_time = asyncio.get_event_loop().time() if asyncio.get_running_loop() else time.time()
        cooldown_remaining = max(0, RESPAWN_COOLDOWN - (current_time - last_respawn))
        
        # Add legend and game stats with horizontal layout and colors
        legend = f"\nLegend: {RENDER_DEAD}=Empty {RENDER_LIVE}=Live {RENDER_PLAYER}=You {RENDER_OTHER_PLAYER}=Other"
        
        game_stats = f" | Gen: {self.generation_count} | Players: {len(self.players)}"
        
        respawn_info = f" | Respawns: {respawn_count} | Cooldown: {cooldown_remaining:.1f}s"
        
        # Add god mode stats if enabled
        god_mode_stats = ""
        if player_state.get('god_mode'):
            live_count = self.get_live_cell_count()
            god_mode_stats = f" | {COLOR_BOLD}GOD MODE ACTIVE{COLOR_RESET} | Live: {live_count} | R=Restart | g=Exit"

        # Add any feedback message
        feedback = ""
        if player_state.get('feedback_message'):
            feedback = f"\n{player_state['feedback_message']}"

        # Add key instructions
        key_instructions = "\nKeys: r=respawn | q=quit"

        # Add respawn confirmation prompt if active (moved after key instructions)
        prompt = ""
        if player_state.get('confirmation_prompt'):
            prompt = f"\n{player_state['confirmation_prompt']}"

        # Add command prompt
        command_prompt = "\nEnter command: "

        # Combine everything with proper spacing and screen clearing
        return CLEAR_SCREEN + '\n'.join(viewport) + legend + game_stats + respawn_info + god_mode_stats + feedback + key_instructions + prompt + command_prompt

# Example usage (only if run directly)
if __name__ == "__main__":
    import asyncio 
    import time

    cols, rows = 80, 24 # Fixed size for direct run example
    try:
         term_cols, term_rows = os.get_terminal_size()
         cols, rows = term_cols, term_rows - 5 # Leave more space for potential prompts
    except OSError:
         pass 

    game = GameOfLife(width=cols, height=rows)
    game.add_player(1)
    game.add_player(99)

    # Simulate player 1 state for testing
    player_1_state = {
         'confirmation_prompt': None, 
         'feedback_message': "Test Feedback!", 
         'feedback_expiry_time': time.time() + 5.0 
         } 

    try:
        while True:
            current_time_test = time.time()
            # Simulate checking expiry
            if player_1_state.get('feedback_message') and current_time_test >= player_1_state.get('feedback_expiry_time', 0.0):
                 player_1_state['feedback_message'] = None
                 player_1_state['feedback_expiry_time'] = 0.0
            
            render_output = game.get_render_string(requesting_player_id=1, player_state=player_1_state) 
            print("\x1b[H\x1b[J" + render_output) # Clear screen
            game.next_generation()
            time.sleep(0.1)

            # Example: Make feedback expire after 5s in test
            # if current_time_test > start_time_test + 5:
            #      player_1_state['feedback_message'] = None

    except KeyboardInterrupt:
        print("\nExiting.")
