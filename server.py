import asyncio
import asyncssh
import sys
import logging
import random
from shutil import get_terminal_size
import os
import signal # Import the signal module
import time

# Import the GameOfLife class and the constant
from game_of_life import GameOfLife, RESPAWN_COOLDOWN

# --- Configuration ---
SERVER_HOST = '0.0.0.0' # Listen on all interfaces
SERVER_PORT = 8022      # Port for SSH connections (make sure it's not used)
GAME_TICK_RATE = 0.1    # Seconds between game generations
SERVER_KEYS = ['ssh_host_key'] # Path to server's private key
LOG_LEVEL = logging.INFO
# --- Game Board Size ---
# Defaults used if terminal size detection fails
DEFAULT_GAME_WIDTH = 100 # Increased default
DEFAULT_GAME_HEIGHT = 45 # Increased default
# --- End Configuration ---

# Setup logging
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(message)s')
log = logging.getLogger(__name__)

# Global state
game: GameOfLife | None = None
clients = {} # player_id -> {'chan': SSH Channel, 'state': {'confirmation_prompt': str | None}}
# pending_connections = {} # REMOVED
next_player_id = 1 # Start player IDs from 1
game_loop_task: asyncio.Task | None = None
shutdown_event = asyncio.Event()

# --- Respawn Confirmation State ---
# State is now stored per-player in the `clients` dictionary
# players_confirming_respawn = set() # REMOVED
# --- End Respawn State ---

# --- Stability Tracking ---
STABILITY_CHECK_TICKS = 20 # Number of ticks count must be stable
last_live_counts = []
is_board_stable = False
# --- End Stability Tracking ---

async def run_game_loop():
    """Task to run the game simulation and check for stability."""
    global game, is_board_stable, last_live_counts
    log.info("Starting game loop...")
    loop_count = 0 # Debug counter
    clear_screen_code = "\x1b[2J\x1b[H"
    while not shutdown_event.is_set():
        if game:
            loop_count += 1
            if loop_count % 10 == 0: # Log every 10 ticks
                log.debug(f"Game loop tick #{loop_count} - Stable: {is_board_stable} - Clients: {list(clients.keys())}")

            start_time = asyncio.get_event_loop().time()

            # --- Update Game State ---
            previous_live_count = game.get_live_cell_count() if last_live_counts else 0
            game.next_generation()
            current_live_count = game.get_live_cell_count()

            # --- Check for Stability ---
            if current_live_count != previous_live_count:
                # If count changed, board is definitely not stable
                if is_board_stable:
                     log.info("Board destabilized (live count changed).")
                is_board_stable = False
                last_live_counts = [current_live_count] # Reset history
            else:
                # Count is the same as last tick, add to history
                if not is_board_stable: # Only check if not already marked stable
                    last_live_counts.append(current_live_count)
                    if len(last_live_counts) > STABILITY_CHECK_TICKS:
                        last_live_counts.pop(0) # Keep history size limited
                    
                    # Check if all recent counts are identical
                    if len(last_live_counts) == STABILITY_CHECK_TICKS and len(set(last_live_counts)) == 1:
                         log.info(f"Board stabilized (live count {current_live_count} constant for {STABILITY_CHECK_TICKS} ticks).")
                         is_board_stable = True
            # --- End Stability Check ---

            # --- Send Updates to Clients ---
            disconnected_players = []
            current_time = asyncio.get_event_loop().time() # Get time once per tick
            
            for player_id, client_data in list(clients.items()): 
                chan = client_data['chan']
                player_state = client_data['state']
                try:
                    # --- Check/Clear Expired Feedback --- 
                    if player_state.get('feedback_message') and current_time >= player_state.get('feedback_expiry_time', 0.0):
                         # log.debug(f"Clearing expired feedback for player {player_id}") # Optional debug
                         player_state['feedback_message'] = None
                         player_state['feedback_expiry_time'] = 0.0
                    # --- End Feedback Check ---
                    
                    # Generate personalized render string, passing player state
                    # current_prompt = player_state.get('confirmation_prompt') # No longer needed here
                    render_str = game.get_render_string(player_id, player_state=player_state)
                    
                    # Logging (FIXED newline formatting)
                    if loop_count % 10 == 1: 
                        # Log state details for debugging
                        log.debug(f"Render state for player {player_id}: {player_state}")
                        # log.debug(f"Render string for player {player_id} (prompt='{current_prompt}'): {render_str[:80].replace('\n', '\\n')}...")

                    # Send game state WITH screen clear
                    chan.write(clear_screen_code + render_str) 

                except (asyncssh.misc.ConnectionLost, BrokenPipeError, OSError) as exc:
                    log.warning(f"Player {player_id} connection lost during update: {exc}")
                    disconnected_players.append(player_id)
                except Exception as exc:
                     log.error(f"Error sending update to player {player_id}: {exc}", exc_info=True)
                     disconnected_players.append(player_id) # Assume connection is broken

            # Remove clients that disconnected during the update phase
            for player_id in disconnected_players:
                if player_id in clients:
                    log.info(f"Removing player {player_id} from clients due to update error.")
                    # Channel is likely already closed, but try closing just in case
                    try:
                         if not clients[player_id]['chan'].is_closing():
                              clients[player_id]['chan'].close()
                    except Exception:
                         pass # Ignore errors during cleanup
                    del clients[player_id]
                    # Game state removal is handled in session connection_lost

            # --- Maintain Tick Rate ---
            elapsed_time = asyncio.get_event_loop().time() - start_time
            sleep_duration = max(0, GAME_TICK_RATE - elapsed_time)
            await asyncio.sleep(sleep_duration)

        else:
            # Wait if game not initialized yet
            await asyncio.sleep(0.5)
    log.info("Game loop stopped.")


# --- SSH Session Class --- 

class GameSSHServerSession(asyncssh.SSHServerSession):
    """Handles a single client's interactive session."""
    def __init__(self, player_id):
        log.debug(f"GameSSHServerSession.__init__ called for player {player_id}")
        self._player_id = player_id
        self._chan = None

    def connection_made(self, chan):
        """Called when the session channel is established."""
        log.debug(f"GameSSHServerSession.connection_made called for player {self._player_id}")
        self._chan = chan
        term = chan.get_terminal_type()
        log.info(f"Player {self._player_id} established session (TERM={term})")

        # Store the active channel and initial state in the main clients dictionary
        clients[self._player_id] = {
             'chan': chan,
             'state': {
                 'confirmation_prompt': None,
                 'feedback_message': None, 
                 'feedback_expiry_time': 0.0
                 } 
         }
        log.debug(f"Player {self._player_id} added to active clients with state.")
        # No need to handle pending_connections anymore

    def pty_requested(self, term_type, term_rows, term_cols) -> bool:
         """Called when the client requests a pseudo-terminal."""
         log.debug(f"Player {self._player_id}: pty_requested (TERM={term_type}, size={term_cols}x{term_rows})")
         return True # Accept PTY request

    def shell_requested(self) -> bool:
        """Called when the client requests an interactive shell."""
        log.debug(f"Player {self._player_id}: shell_requested.")
        return True # Accept the shell request

    def session_started(self):
        """Called when the session is fully started (after shell/exec/pty)."""
        log.info(f"Player {self._player_id}: Session started.")
        # Removed the code that tried to create the handle_client_input task
        # Input is now handled by data_received

    def data_received(self, data, datatype):
        """Called when data is received from the client.
        Handles Ctrl+C (ETX), 'q' (quit), and 'r' (respawn).
        Adaptively handles bytes or string input.
        Uses player state for respawn confirmation prompt.
        """
        # --- DEBUG: Log raw received data --- 
        log.debug(f"Player {self._player_id} RAW INPUT: data={data!r} (type: {type(data)}), datatype={datatype}")
        # --- End DEBUG --- 
        
        # Need access to game, and clients dict to modify state
        global game, clients 
        action_taken = False
        feedback_msg = None # For temporary messages like success/failure
        data_str = None 

        # --- Handle Input Actions (Type detection) ---
        if isinstance(data, bytes):
            # Check for Ctrl+C (raw bytes)
            if data == b'\x03':
                log.info(f"Player {self._player_id} requested disconnect (Ctrl+C). Closing connection.")
                if self._chan and not self._chan.is_closing():
                    self._chan.close() 
                action_taken = True
                return 
            else:
                try:
                    data_str = data.decode('utf-8', errors='ignore').lower().strip()
                except Exception as e:
                    log.warning(f"Player {self._player_id}: Error decoding byte input {data!r}: {e}")
                    data_str = None 
        elif isinstance(data, str):
            data_str = data.lower().strip()
        # --- End Input Type Handling ---

        # Get current player state (if connected)
        client_data = clients.get(self._player_id)
        player_state = client_data.get('state') if client_data else None

        # --- Try processing the input based on state and string --- 
        try:
            if player_state is None:
                 log.warning(f"Player {self._player_id} sent input but has no client_data entry.")
                 return # Cannot process further

            # --- Check for pending Respawn Confirmation --- 
            is_confirming = player_state.get('confirmation_prompt') is not None
            if is_confirming:
                confirmation_key = data_str # The key pressed during confirmation
                player_state['confirmation_prompt'] = None # Clear prompt state immediately
                current_time = asyncio.get_event_loop().time() if asyncio.get_running_loop() else time.time()
                result_message = None

                if confirmation_key == 'y':
                    log.info(f"Player {self._player_id} confirmed respawn ('y').")
                    if game:
                         success, message = game.respawn_player(self._player_id)
                         log.info(f"Player {self._player_id} respawn result: Success={success}, Msg: {message}")
                         result_message = message # Use message from respawn
                    else:
                         result_message = "Game not ready for respawn."
                elif confirmation_key == 'n':
                     log.info(f"Player {self._player_id} cancelled respawn ('n').")
                     result_message = "Respawn cancelled."
                else:
                     log.info(f"Player {self._player_id} gave invalid respawn confirmation ('{confirmation_key}'). Cancelling.")
                     result_message = f"Invalid confirmation '{confirmation_key}'. Respawn cancelled."
                
                # Set feedback state instead of sending message directly
                if result_message:
                     player_state['feedback_message'] = result_message
                     player_state['feedback_expiry_time'] = current_time + 3.0

                action_taken = True 
                # Prompt cleared, state set, let render loop show feedback
            
            # --- Process regular commands if no confirmation pending and data_str is valid --- 
            elif data_str is not None:
                if data_str == 'q':
                    log.info(f"Player {self._player_id} requested disconnect ('q'). Closing connection.")
                    if self._chan and not self._chan.is_closing():
                        self._chan.close() 
                    action_taken = True
                    return 

                # Check for 'r' (Initiate Respawn)
                elif data_str == 'r':
                    log.debug(f"Player {self._player_id} pressed 'r' - checking cooldown.")
                    # feedback_msg = None # No direct feedback for initiating
                    if game:
                        player_game_data = game.players.get(self._player_id)
                        on_cooldown = False
                        if player_game_data:
                            current_time = asyncio.get_event_loop().time() if asyncio.get_running_loop() else time.time()
                            last_respawn = player_game_data.get('last_respawn_time', 0)
                            time_since_respawn = current_time - last_respawn
                            if time_since_respawn < RESPAWN_COOLDOWN: 
                                on_cooldown = True
                                remaining = RESPAWN_COOLDOWN - time_since_respawn
                                log.info(f"Player {self._player_id} tried respawn during cooldown ({remaining:.1f}s left).")
                        
                        # Set confirmation prompt if not on cooldown
                        if not on_cooldown:
                            log.info(f"Player {self._player_id} initiating respawn confirmation.")
                            player_state['confirmation_prompt'] = "Respawn clears ALL your cells. Confirm? (y/n)" 
                            # Clear any lingering feedback message when prompt appears
                            player_state['feedback_message'] = None
                            player_state['feedback_expiry_time'] = 0.0
                        # else: Cooldown check handled above (no feedback)
                    else:
                        # Set feedback state for this error case
                        current_time = asyncio.get_event_loop().time() if asyncio.get_running_loop() else time.time()
                        player_state['feedback_message'] = "Game not ready for respawn."
                        player_state['feedback_expiry_time'] = current_time + 3.0
                    action_taken = True
                
                # Log unhandled characters 
                elif not action_taken and data_str: 
                    log.debug(f"Player {self._player_id} sent unhandled string data: '{data_str}', Original: {data!r}")

            # 4. Log if input type was unexpected 
            elif not action_taken and not isinstance(data, bytes): 
                log.debug(f"Player {self._player_id} sent unhandled data type: {data!r} (type: {type(data)}), datatype={datatype}.")

        except Exception as e:
            log.error(f"Player {self._player_id}: **** Unhandled exception during input processing for '{data_str}': {e} ****", exc_info=True)
            # feedback_msg = "\r\nAn internal error occurred processing your request.\r\n"
            # Set feedback state for errors
            if player_state:
                 current_time = asyncio.get_event_loop().time() if asyncio.get_running_loop() else time.time()
                 player_state['feedback_message'] = "An internal error occurred processing your request."
                 player_state['feedback_expiry_time'] = current_time + 3.0
                 player_state['confirmation_prompt'] = None # Clear prompt on error too
            action_taken = True 
        # --- End Try/Except Block for action handling ---

    def connection_lost(self, exc):
        """Called when the session channel is lost."""
        log.info(f"Player {self._player_id}: Session connection_lost. Reason: {exc if exc else 'Closed gracefully'}")
        # Remove player entry from clients dict (handles channel and state)
        if self._player_id in clients:
            log.debug(f"Removing player {self._player_id} entry from clients dict in Session.connection_lost.")
            del clients[self._player_id]
        
        # players_confirming_respawn.discard(self._player_id) # REMOVED - State was in clients dict
        # log.debug(f"Ensured player {self._player_id} is removed from players_confirming_respawn set.")
        
        global game
        if game and self._player_id is not None:
            log.debug(f"Removing player {self._player_id} from game state.")
            game.remove_player(self._player_id)
        log.debug(f"Finished Session.connection_lost for player {self._player_id}.")


# --- SSH Server Factory --- 

class GameSSHServer(asyncssh.SSHServer):
    """Handles incoming SSH connections and creates session instances."""
    def __init__(self):
        # Initialize instance variable for player_id
        self._player_id = None
        log.debug("GameSSHServer.__init__ called (new connection instance)")

    def connection_made(self, conn):
        """Called when a new SSH connection is established (pre-auth)."""
        log.debug(f"GameSSHServer.connection_made for {conn.get_extra_info('peername')}")
        global next_player_id, game, is_board_stable
        # Assign player ID to instance variable
        self._player_id = next_player_id 
        next_player_id += 1
        log.info(f"Assigned player ID {self._player_id} to this connection instance from {conn.get_extra_info('peername')[0] if conn.get_extra_info('peername') else 'unknown'}")

        if not game:
             log.error("Game not initialized when player connected! Closing.")
             conn.close()
             return

        # Add player to game state 
        # Inject disruption if the board is currently stable
        if game.add_player(self._player_id, inject_disruption=is_board_stable):
            log.info(f"Player {self._player_id} added to game state. (Disruption injected: {is_board_stable})")
            # If disruption was injected, manually reset the stability flag
            if is_board_stable:
                 log.info("Resetting stability flag due to player join disruption.")
                 global last_live_counts # Need global to modify
                 is_board_stable = False
                 last_live_counts = [] # Clear history
        else:
            log.warning(f"Failed to add player {self._player_id} to game board. Closing connection.")
            conn.close()
            # No return needed here, let connection_lost handle cleanup if it closes

    def connection_lost(self, exc):
        """Called when the initial connection is lost (before session starts)."""
        # Player ID might be None if connection_made didn't complete
        pid = self._player_id if hasattr(self, '_player_id') else 'unknown'
        log.warning(f"Initial connection lost for player {pid} before session started. Reason: {exc if exc else 'Closed gracefully'}")
        # Attempt to remove player from game state if they were added
        global game
        if game and self._player_id is not None:
             # Check if player exists before trying to remove
             # This might be redundant if game.remove_player handles non-existent players gracefully
             log.debug(f"Attempting cleanup for player {self._player_id} in GameSSHServer.connection_lost")
             game.remove_player(self._player_id)
        # No pending_connections dict to clean anymore

    def begin_auth(self, username):
        """Use instance player_id for logging."""
        log.debug(f"Player {self._player_id}: begin_auth for user '{username}'")
        return False # No auth required

    def auth_completed(self):
        """Use instance player_id for logging."""
        log.info(f"Player {self._player_id}: Auth completed.")

    def session_requested(self):
        """Use instance player_id to create the session."""
        if self._player_id is None:
            # This shouldn't happen if connection_made succeeded
            log.error(f"Session requested but player_id is None for this connection. Refusing session.")
            return None
        
        log.debug(f"GameSSHServer creating GameSSHServerSession for player {self._player_id}")
        return GameSSHServerSession(self._player_id)

# --- Server Startup --- 

async def start_server():
    """Starts the SSH server and the game loop."""
    global game, game_loop_task

    log.info("Attempting to load/generate server host key...")
    try:
        # Explicitly check if file exists before trying to generate
        key_path = SERVER_KEYS[0]
        if not os.path.exists(key_path):
             log.info(f"Key file '{key_path}' not found. Generating new key...")
             # Generate the key object first (synchronous call)
             key = asyncssh.generate_private_key('ssh-ed25519')
             # Now write it to the specified file path
             key.write_private_key(key_path)
             log.info(f"Generated and saved new server key: {key_path}")
        else:
             log.info(f"Using existing server key: {key_path}")
        # We can also try loading the key here to ensure it's valid, though create_server usually handles this
    except Exception as e:
         log.error(f"FATAL: Failed during server key handling for '{SERVER_KEYS[0]}': {e}", exc_info=True)
         return # Stop execution if key handling fails

    log.info("Host key check/generation complete.")

    log.info("Attempting to initialize game board...")
    try:
        # Use terminal size if possible
        try:
            cols, rows = get_terminal_size()
            # Use full height, width might need adjustment depending on client rendering
            game_height = max(10, rows) # Use a minimum height
            game_width = max(20, cols) # Use a minimum width
            log.info(f"Terminal size detected: {cols}x{rows}. Initializing game board with size: {game_width}x{game_height}")
        except OSError as e:
            log.warning(f"Could not detect terminal size: {e}. Using default {DEFAULT_GAME_WIDTH}x{DEFAULT_GAME_HEIGHT}.")
            game_width = DEFAULT_GAME_WIDTH
            game_height = DEFAULT_GAME_HEIGHT
        
        game = GameOfLife(width=game_width, height=game_height)
        log.info("Game board initialized successfully.")
    except Exception as e: # Catch other potential GameOfLife init errors
         log.error(f"FATAL: Failed to initialize GameOfLife: {e}", exc_info=True)
         return # Stop execution

    log.info("Game initialization complete.")

    # Start the game loop as a background task
    log.info("Attempting to start game loop task...")
    try:
        game_loop_task = asyncio.create_task(run_game_loop())
        log.info("Game loop task created successfully.")
    except Exception as e:
         log.error(f"FATAL: Failed to create game loop task: {e}", exc_info=True)
         return # Stop execution if task creation fails


    log.info(f"Attempting to start SSH server on {SERVER_HOST}:{SERVER_PORT}...")
    server = None # Keep track of the server object for shutdown
    try:
        server = await asyncssh.create_server(
            GameSSHServer, SERVER_HOST, SERVER_PORT,
            server_host_keys=SERVER_KEYS,
            # process_factory=lambda proc: proc # REMOVED - Let asyncssh handle sessions internally
        )
        log.info(f"SSH Server started successfully and listening on {SERVER_HOST}:{SERVER_PORT}.")
    except Exception as e:
        log.error(f"FATAL: Failed to start SSH server: {e}", exc_info=True)
        shutdown_event.set() # Signal game loop to stop if it started
        if game_loop_task:
            await game_loop_task
        return

    # Keep server running until shutdown is signaled
    log.info("Server setup complete. Waiting for connections or shutdown signal...")
    await shutdown_event.wait()

    # --- Shutdown sequence ---
    log.info("Shutdown signal received.")

    # Explicitly cancel game loop task first
    if game_loop_task and not game_loop_task.done():
        log.info("Attempting to cancel game loop task...")
        game_loop_task.cancel()
        try:
            # Give it a chance to process cancellation
            await game_loop_task
        except asyncio.CancelledError:
            log.info("Game loop task successfully cancelled.")
        except Exception as e:
            log.error(f"Error during game loop task cancellation/await: {e}", exc_info=True)
        finally:
            log.info("Game loop task processing complete after shutdown signal.")

    if server:
        log.info("Closing SSH server...")
        server.close()
        await server.wait_closed()
        log.info("SSH server closed.")

    # No longer need to await game_loop_task here as it was handled above
    # (Removed the redundant await/log block for game_loop_task)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    # --- Add Signal Handling --- 
    def handle_signal(sig, frame):
        log.warning(f"Received signal {sig}, initiating shutdown...")
        # Avoid calling set() multiple times if signal received rapidly
        if not shutdown_event.is_set(): 
            shutdown_event.set()

    try:
        # Add signal handlers for graceful shutdown
        loop.add_signal_handler(signal.SIGINT, handle_signal, signal.SIGINT, None)
        loop.add_signal_handler(signal.SIGTERM, handle_signal, signal.SIGTERM, None)
        log.info(f"Registered signal handlers for SIGINT and SIGTERM.")
    except NotImplementedError:
        # Windows doesn't support add_signal_handler, KeyboardInterrupt is primary mechanism
        log.warning("add_signal_handler not supported on this platform (likely Windows). Relying on KeyboardInterrupt.")
    # --- End Signal Handling ---

    try:
        log.info("Starting server...")
        # Start the server and wait for it to complete (which it won't until shutdown)
        loop.run_until_complete(start_server())
    except (OSError, asyncssh.Error) as exc:
        sys.exit(f'Error starting server: {exc}')
    except KeyboardInterrupt:
        # This might still trigger on Windows or if signal handlers fail
        log.info("Shutdown requested via KeyboardInterrupt (or signal). Handling...")
        if not shutdown_event.is_set():
            shutdown_event.set() # Ensure shutdown event is set
    finally:
        log.info("Entering final cleanup...")
        # Ensure shutdown_event is set if loop terminates unexpectedly
        if not shutdown_event.is_set():
            log.warning("Loop terminated unexpectedly, forcing shutdown signal.")
            shutdown_event.set()

        # Give tasks a moment to shut down gracefully
        # Gather tasks that need awaiting (should primarily be game_loop_task if start_server returned)
        # Note: server.wait_closed() is awaited within start_server's shutdown sequence
        tasks = [task for task in asyncio.all_tasks(loop) if task is not asyncio.current_task(loop)]
        
        # Check if game_loop_task exists and is among the tasks to await
        if game_loop_task and game_loop_task in tasks:
            log.debug(f"Explicitly identified game_loop_task ({game_loop_task.get_name()}) for final await.")
        elif game_loop_task and not game_loop_task.done():
            log.warning("game_loop_task exists but wasn't in asyncio.all_tasks? Adding it manually.")
            tasks.append(game_loop_task) # Ensure it's awaited if somehow missed

        if tasks:
            log.info(f"Waiting for {len(tasks)} background tasks to complete...")
            # Use a timeout to prevent hanging indefinitely if a task misbehaves
            try:
                loop.run_until_complete(asyncio.wait(tasks, timeout=5.0))
                log.info("Background tasks completed or timed out.")
            except Exception as e:
                log.error(f"Error during task gathering/waiting: {e}")
        else:
             log.info("No background tasks found needing explicit cleanup.")

        # Close the loop
        log.info("Closing event loop...")
        loop.close()
        log.info("Server shut down cleanly.") 