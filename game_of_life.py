import random
import os
import asyncio
import time
import sys
import termios
import tty

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
RENDER_DEAD = " "  # Space for dead cells
RENDER_LIVE = "█"  # Block for live cells
RENDER_PLAYER = "★"  # Star for player
RENDER_OTHER_PLAYER = "●"  # Dot for other players

# Screen handling codes
CLEAR_SCREEN = "\033[2J\033[H"  # Clear screen and move cursor to top
CLEAR_LINE = "\033[K"  # Clear current line
CLEAR_TO_END = "\033[J"  # Clear from cursor to end of screen
CLEAR_ALL = "\033[2J\033[H\033[3J"  # Clear screen, scrollback buffer, and move cursor to top
HIDE_CURSOR = "\033[?25l"  # Hide cursor
SHOW_CURSOR = "\033[?25h"  # Show cursor
SAVE_CURSOR = "\033[s"  # Save cursor position
RESTORE_CURSOR = "\033[u"  # Restore cursor position

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
    "block": [(0, 0), (0, 1), (1, 0), (1, 1)],
    "blinker_h": [(0,0), (0,1), (0,2)], # Horizontal Blinker (period 2 oscillator)
    "lwss": [(0,1), (0,4), (1,0), (2,0), (2,4), (3,0), (3,1), (3,2), (3,3)], # LightWeight SpaceShip
    "glider": [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)], # Add glider back as a pattern
    "beacon": [(0,0), (0,1), (1,0), (1,1), (2,2), (2,3), (3,2), (3,3)], # Beacon pattern
    "toad": [(0,1), (0,2), (0,3), (1,0), (1,1), (1,2)] # Toad pattern
}
STANDARD_PATTERN_DIMS = {
    "block": (2, 2),
    "blinker_h": (1, 3),
    "lwss": (4, 5),
    "glider": (3, 3),
    "beacon": (4, 4),
    "toad": (2, 4)
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
        # Use more varied patterns
        patterns_to_seed = [
            ("block", num_blocks),
            ("blinker_h", num_blinkers),
            ("lwss", num_lwss),
            ("beacon", 2),  # Add some beacons
            ("toad", 2),    # Add some toads
            ("glider", 3)   # Add some gliders
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
                    
                    # Basic overlap check with increased spacing
                    too_close = False
                    proximity = max(p_width, p_height) + 4  # Increased minimum distance between patterns
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

        # Track current leader before generation
        current_leader = None
        max_cells = 0
        for pid in self.players:
            cell_count = self.get_player_cell_count(pid)
            if cell_count > max_cells:
                max_cells = cell_count
                current_leader = pid

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
        self.generation_count += 1

        # Update generations in lead for current leader
        if current_leader is not None:
            if 'generations_in_lead' not in self.players[current_leader]:
                self.players[current_leader]['generations_in_lead'] = 0
            self.players[current_leader]['generations_in_lead'] += 1

        # Check if we've reached 2500 generations
        if self.generation_count >= 2500:
            # Find the winner (player with most generations in lead)
            winner = max(self.players.items(), key=lambda x: x[1].get('generations_in_lead', 0))[0]
            
            # Increment win counter for the winner
            if winner in self.players:
                if 'wins' not in self.players[winner]:
                    self.players[winner]['wins'] = 0
                self.players[winner]['wins'] += 1
                print(f"DEBUG: Player {winner} won! Total wins: {self.players[winner]['wins']}")  # Debug print
            
            # Reset generation count
            self.generation_count = 0
            
            # Reset generations in lead for all players
            for pid in self.players:
                self.players[pid]['generations_in_lead'] = 0
            
            # Set auto reset flag for this reset cycle
            self._auto_reset = True
            
            # Perform god mode restart
            for pid in list(self.players.keys()):
                if pid in self.players:
                    self.respawn_player(pid, is_god_mode=True)
            
            # Clear auto reset flag after restart
            delattr(self, '_auto_reset')

    def add_player(self, player_id, inject_disruption=False):
        """Adds a player pattern, initializes their stats, and optionally injects disruption."""
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
                     'respawn_count': 0,
                     'wins': 0  # Initialize win counter
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
            
            # 3. Reset win counters (only for manual god mode reset)
            if not hasattr(self, '_auto_reset'):  # Only reset wins if this is a manual reset
                print(f"DEBUG: Manual god mode reset - resetting win counters")  # Debug print
                for pid in self.players:
                    self.players[pid]['wins'] = 0
            else:
                print(f"DEBUG: Auto reset - preserving win counters")  # Debug print
            
            # 4. Calculate available space for players
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
            
            # 5. Add all players back with increased max attempts
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
            # Regular respawn: Only remove player cells and respawn nearby
            # 1. Get the player's current position
            current_pos = player_data.get('pos')
            if not current_pos:
                print(f"WARN: Player {player_id} has no position data")
                return (False, "Respawn failed: No position data found")

            # 2. Remove only the player's cells
            removed_count = 0
            for r in range(self.height):
                for c in range(self.width):
                    if self.grid[r][c] == player_id:
                        self.grid[r][c] = INTERNAL_DEAD
                        removed_count += 1

            # 3. Try to respawn near the current position
            # Start with a small offset and gradually increase if needed
            max_offset = 5  # Maximum distance to try from current position
            success = False
            new_pos = None

            for offset in range(1, max_offset + 1):
                # Try different directions around the current position
                for dr in [-offset, 0, offset]:
                    for dc in [-offset, 0, offset]:
                        if dr == 0 and dc == 0:
                            continue  # Skip current position
                        
                        # Calculate new position with wrapping
                        new_r = (current_pos[0] + dr) % self.height
                        new_c = (current_pos[1] + dc) % self.width
                        
                        # Check if we can place the pattern here
                        if self._is_area_clear(new_r, new_c, PLAYER_SPAWN_PATTERN):
                            # Place the pattern
                            self._place_pattern(new_r, new_c, PLAYER_SPAWN_PATTERN, player_id)
                            new_pos = (new_r, new_c)
                            success = True
                            break
                    if success:
                        break
                if success:
                    break

            if success:
                # 4. Update player stats
                self.players[player_id]['last_respawn_time'] = current_time
                self.players[player_id]['respawn_count'] = old_respawn_count + 1
                self.players[player_id]['pos'] = new_pos
                # Add moving trait
                self.players[player_id]['moving'] = True
                self.players[player_id]['move_direction'] = (0, 1)  # Start moving right
                print(f"DEBUG: Player {player_id} respawned near position {new_pos}. Count: {self.players[player_id]['respawn_count']}")
                return (True, "Respawn successful!")
            else:
                print(f"WARN: Failed to find spot near current position for player {player_id} during respawn.")
                return (False, "Respawn failed: Could not find empty space nearby.")

    def get_live_cell_count(self):
        """Counts the total number of live cells (standard and player-owned)."""
        count = 0
        for r in range(self.height):
            for c in range(self.width):
                if self.grid[r][c] != INTERNAL_DEAD:
                    count += 1
        return count

    def get_player_cell_count(self, player_id):
        """Counts the number of cells owned by a specific player."""
        count = 0
        for r in range(self.height):
            for c in range(self.width):
                if self.grid[r][c] == player_id:
                    count += 1
        return count

    def get_render_string(self, requesting_player_id, player_state):
        """Generates the game board render string with player-specific view."""
        # Get the player's position if they exist
        player_pos = self.players.get(requesting_player_id, {}).get('pos')
        if not player_pos:
            return "Error: Player not found in game state."

        # Get terminal size for responsive viewport
        try:
            term_cols, term_rows = os.get_terminal_size()
            # Use 80% of terminal width and 50% of terminal height
            view_width = int(term_cols * 0.8)
            view_height = int(term_rows * 0.5)
            # Ensure minimum size
            view_width = max(60, view_width)
            view_height = max(30, view_height)
        except OSError:
            # Fallback to default sizes if terminal size detection fails
            view_width = 80
            view_height = 40

        # Start with a simple screen clear and cursor handling
        render_output = CLEAR_SCREEN + HIDE_CURSOR

        center_r, center_c = player_pos

        # Calculate viewport boundaries with wrapping
        start_r = (center_r - view_height // 2) % self.height
        start_c = (center_c - view_width // 2) % self.width

        # Build the viewport with pre-allocated list for better performance
        viewport = [''] * view_height
        for i in range(view_height):
            row = [''] * view_width
            for j in range(view_width):
                # Calculate actual grid position with wrapping
                r = (start_r + i) % self.height
                c = (start_c + j) % self.width
                cell = self.grid[r][c]
                
                # Determine what to display
                if cell == INTERNAL_DEAD:
                    row[j] = RENDER_DEAD
                elif cell == INTERNAL_LIVE:
                    row[j] = RENDER_LIVE
                elif cell == requesting_player_id:
                    row[j] = RENDER_PLAYER
                else:
                    row[j] = RENDER_OTHER_PLAYER
            viewport[i] = ''.join(row)

        # Build the status line
        player_data = self.players.get(requesting_player_id, {})
        respawn_count = player_data.get('respawn_count', 0)
        wins = player_data.get('wins', 0)
        last_respawn = player_data.get('last_respawn_time', 0)
        current_time = asyncio.get_event_loop().time() if asyncio.get_running_loop() else time.time()
        cooldown_remaining = max(0, RESPAWN_COOLDOWN - (current_time - last_respawn))
        
        # Pre-build all sections for better performance
        overview = f"\n{COLOR_BOLD}Game of Life - Multiplayer Edition{COLOR_RESET}"
        overview += f"\nActive Players: {len(self.players)} | Current Generation: {self.generation_count}/2500"
        overview += f"\nYour Wins: {wins} | Respawns: {respawn_count} | Cooldown: {cooldown_remaining:.1f}s"
        overview += "\n"
        
        legend = f"\nLegend: {RENDER_DEAD}=Empty {RENDER_LIVE}=Live {RENDER_PLAYER}=You {RENDER_OTHER_PLAYER}=Other"
        
        # Add key instructions
        key_instructions = "\nKeys: r=respawn | q=quit"
        if player_state.get('debug_mode') or player_state.get('god_mode'):
            key_instructions += " | h=hot reload"
        key_instructions += "\n"

        # Generate leaderboard
        player_scores = []
        for pid in self.players:
            cell_count = self.get_player_cell_count(pid)
            generations_in_lead = self.players[pid].get('generations_in_lead', 0)
            player_scores.append((pid, cell_count, generations_in_lead))
        
        player_scores.sort(key=lambda x: x[1], reverse=True)
        top_3 = player_scores[:3]
        
        leaderboard = "\nTop 3 Players:"
        all_time_leader = max(self.players.items(), key=lambda x: x[1].get('generations_in_lead', 0))[0] if self.players else None
        
        for i in range(1, 4):
            if i <= len(top_3):
                pid, score, gens = top_3[i-1]
                player_text = "me" if pid == requesting_player_id else f"Player {pid}"
                row = f"{i}. {player_text}: {score} cells (Leader for {gens} gens)"
                if pid == requesting_player_id:
                    if pid == all_time_leader:
                        row = f"{COLOR_BOLD}{COLOR_PLAYER}{row}{COLOR_RESET}"
                    else:
                        row = f"{COLOR_BOLD}\033[38;5;40m{row}{COLOR_RESET}"
                elif pid == all_time_leader:
                    row = f"{COLOR_BOLD}{COLOR_PLAYER}{row}{COLOR_RESET}"
            else:
                row = f"{i}. Waiting for players..."
            leaderboard += f"\n{row}"
        leaderboard += "\n"

        # Build messages section
        messages = []
        if player_state.get('confirmation_prompt'):
            messages.append(player_state['confirmation_prompt'])
        if player_state.get('feedback_message'):
            messages.append(player_state['feedback_message'])
        command_prompt = "\nEnter command: "

        # Combine everything with proper spacing and restore cursor
        return render_output + '\n'.join(viewport) + overview + legend + key_instructions + leaderboard + '\n'.join(messages) + command_prompt + SHOW_CURSOR

# Example usage (only if run directly)
if __name__ == "__main__":
    import asyncio 
    import time

    cols, rows = 80, 24
    try:
         term_cols, term_rows = os.get_terminal_size()
         cols, rows = term_cols, term_rows - 5
    except OSError:
         pass 

    game = GameOfLife(width=cols, height=rows)
    game.add_player(1)
    game.add_player(99)

    player_1_state = {
         'confirmation_prompt': None, 
         'feedback_message': "Test Feedback!", 
         'feedback_expiry_time': time.time() + 5.0 
         } 

    try:
        # Set terminal to raw mode
        tty.setraw(sys.stdin.fileno())
        
        while True:
            current_time_test = time.time()
            if player_1_state.get('feedback_message') and current_time_test >= player_1_state.get('feedback_expiry_time', 0.0):
                 player_1_state['feedback_message'] = None
                 player_1_state['feedback_expiry_time'] = 0.0
            
            render_output = game.get_render_string(requesting_player_id=1, player_state=player_1_state) 
            sys.stdout.write(render_output)
            sys.stdout.flush()
            game.next_generation()
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        # Restore terminal settings
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        print(SHOW_CURSOR)  # Ensure cursor is shown on exit
