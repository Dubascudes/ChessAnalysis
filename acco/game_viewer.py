#!/usr/bin/env python3
"""
game_viewer.py

Tkinter GUI to browse Chess.com games,
step through them move-by-move, and display per-game metadata
including Stockfish evaluation.
"""

import sqlite3
import io
import re
import json
import tkinter as tk
from tkinter import ttk
from tkinter import simpledialog
from tkinter import messagebox
from PIL import Image, ImageTk
import pathlib
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
import glob
import datetime
import matplotlib.dates as mdates

import chess
import chess.pgn
import chess.svg
import chess.engine
# import cairosvg # Old import
from svglib.svglib import svg2rlg # New import for SVG parsing
from reportlab.graphics import renderPM # New import for PNG rendering
from .settings import SettingsDialog

# For PyInstaller resource path
import sys
import platform

STOCKFISH_PATH = USER = DB_FILE = "" 

# Helper function for PyInstaller
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # In development, _MEIPASS is not set
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# color definitions for game list
COLORS = {
    "win_white": "#90EE90",    # light green for white wins
    "win_black": "#006400",    # dark green for black wins
    "loss_white": "#FF0000",   # bright red for white losses
    "loss_black": "#FFCCCC",   # light red for black losses
    "draw":      "#828282",    # gray for draws
}

class GameViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Chess Analysis Tool")
        self.geometry("1800x700")
        
        try:
            self.state('zoomed')
        except:
            self.attributes('-zoomed', True)
            self.state('normal')

        self.load_settings()
        self.current_user = USER

        # Determine Stockfish executable name based on OS
        # if platform.system() == "Windows":
        #     stockfish_exe_name = "stockfish.exe"
        # else:
        #     stockfish_exe_name = "resources/stockfish" # For Linux and macOS

        
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        except Exception as e:
            messagebox.showerror("Stockfish Error", 
                                 f"Could not start Stockfish engine from: {STOCKFISH_PATH}\n"
                                 f"Ensure Stockfish is included in the application files.\nError: {e}")
            self.engine = None # Fallback
            # Consider if you want to sys.exit(1) or disable engine-dependent features

        self.history = []
        self.original_colors = {}
        
        self.game_white_player = None
        self.game_black_player = None
        
        self.selected_game_pgn = None
        self.selected_game_url = None
        self.selected_game_white_player_name = None
        self.selected_game_black_player_name = None
        
        # Variables for caching ELO plot data
        self._current_elo_plot_user = None
        self._cached_processed_games_for_user = []
        
        # Initialize database - ensure evaluation_data column exists
        # Removed player_summary table creation and player_analysis column management related to T-scores
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA table_info(games)")
            columns = [info[1] for info in cur.fetchall()]
            if 'evaluation_data' not in columns:
                cur.execute("ALTER TABLE games ADD COLUMN evaluation_data TEXT")
                print("Added evaluation_data column to database games table.")
            # Ensure player_analysis column is NOT specifically managed here for T-scores anymore
            # If other features were to use it, their setup would handle it.
            # For T-score removal, we stop interacting with it.
        except sqlite3.OperationalError as e:
            print(f"Error modifying games table: {e}")
        conn.commit()
        conn.close()

        self.main_container = ttk.Frame(self)
        self.main_container.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        left_container = ttk.Frame(self)
        left_container.pack(side="left", fill="both", expand=True, padx=(10,0), pady=10)

        analysis_frame = ttk.Frame(left_container)
        analysis_frame.pack(fill="both", expand=True)

        toggle_frame = ttk.Frame(analysis_frame)
        toggle_frame.pack(fill="x", padx=5, pady=5)
        
        self.analysis_type = tk.StringVar(value="player")
        ttk.Radiobutton(toggle_frame, text="Player Info", 
                       variable=self.analysis_type, value="player",
                       command=self.switch_analysis_view).pack(side="left", padx=5)
        ttk.Radiobutton(toggle_frame, text="Game Info", 
                       variable=self.analysis_type, value="evaluation",
                       command=self.switch_analysis_view).pack(side="left", padx=5)
        
        self.analysis_container = ttk.Frame(analysis_frame)
        self.analysis_container.pack(fill="both", expand=True)
        
        # Game Evaluation Plot Area (Stockfish scores)
        self.plot_frame = ttk.Frame(self.analysis_container)
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(6, 6), height_ratios=[1, 1])
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Player Analysis Frame (primarily for ELO plot now)
        self.player_frame = ttk.LabelFrame(self.analysis_container, text=f"Analysis for {self.current_user}")
        # Packing of self.player_frame handled by switch_analysis_view

        # ELO plot area within player_frame
        self.player_elo_canvas_frame = ttk.Frame(self.player_frame)
        self.player_elo_canvas_frame.pack(fill="both", expand=True, padx=5, pady=(5,0)) # Fill available space, pad bottom
        self.player_elo_fig, self.player_elo_ax = plt.subplots(figsize=(6, 3.5)) # Adjusted fig size a bit
        self.player_elo_canvas = FigureCanvasTkAgg(self.player_elo_fig, master=self.player_elo_canvas_frame)
        self.player_elo_canvas.get_tk_widget().pack(fill="both", expand=True)

        # Frame for ELO controls (start and end game sliders)
        self.elo_controls_frame = ttk.Frame(self.player_frame)
        self.elo_controls_frame.pack(fill="x", padx=5, pady=(0,5))

        ttk.Label(self.elo_controls_frame, text="Start Game:").pack(side="left", padx=(0, 2))
        self.elo_start_slider = ttk.Scale(self.elo_controls_frame, from_=1, to=1, orient="horizontal",
                                         command=lambda value: self.on_elo_range_change(value))
        self.elo_start_slider.pack(side="left", fill="x", expand=True, padx=(0,5))
        self.elo_start_slider.set(1)

        ttk.Label(self.elo_controls_frame, text="End Game:").pack(side="left", padx=(5, 2))
        self.elo_end_slider = ttk.Scale(self.elo_controls_frame, from_=1, to=1, orient="horizontal",
                                       command=lambda value: self.on_elo_range_change(value))
        self.elo_end_slider.pack(side="left", fill="x", expand=True)
        self.elo_end_slider.set(1)
        
        # Frame for ELO time control filters
        self.elo_time_control_filter_frame = ttk.Frame(self.player_frame)
        self.elo_time_control_filter_frame.pack(fill="x", padx=5, pady=(0,5))
        self.time_control_vars = {} # To store BooleanVars for time control checkboxes
        self.time_control_colors = {} # To store colors for time controls
        
        self.plot_elo_history(self.current_user, self.player_elo_ax, self.current_user)
        self.player_elo_fig.tight_layout()
        self.player_elo_canvas.draw()
        
        self.switch_analysis_view()

        self.listbox = tk.Listbox(left_container, width=60, selectmode='single', activestyle='none')
        self.listbox.pack(fill="both", expand=True, pady=(10,0))
        self.listbox.bind("<<ListboxSelect>>", self.on_game_select)
        self.listbox.configure(selectbackground='yellow', selectforeground='black')

        right = ttk.Frame(self.main_container)
        right.pack(side="left", fill="both", expand=True)

        self.players_label = ttk.Label(right, text="", font=("TkDefaultFont", 12, "bold"))
        self.players_label.pack(pady=(0, 10))

        self.board_label = ttk.Label(right)
        self.board_label.pack()

        ctrl = ttk.Frame(right)
        ctrl.pack(pady=5)
        ttk.Button(ctrl, text="⏮ Start", command=self.go_start).pack(side="left")
        ttk.Button(ctrl, text="◀ Prev",  command=self.go_prev).pack(side="left", padx=5)
        ttk.Button(ctrl, text="Next ▶",  command=self.go_next).pack(side="left", padx=5)
        ttk.Button(ctrl, text="⏭ End",   command=self.go_end).pack(side="left")

        self.turn_slider_frame = ttk.Frame(right)
        self.turn_slider_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(self.turn_slider_frame, text="Turn:").pack(side="left")
        self.turn_slider = ttk.Scale(self.turn_slider_frame, from_=0, to=0, orient="horizontal", 
                                   command=self.on_slider_change)
        self.turn_slider.pack(side="left", fill="x", expand=True)

        control_buttons = ttk.Frame(right)
        control_buttons.pack(pady=5)
        
        self.btn_top3 = ttk.Button(control_buttons, text="Show Top 3", 
                                  command=self.show_top3_moves, width=15)
        self.btn_top3.pack(side="left", padx=5)
        
        self.btn_back = ttk.Button(control_buttons, text="Back", 
                                 command=self.show_back, state="disabled", width=20)
        self.btn_back.pack(side="left", padx=5)
        
        self.btn_analyze = ttk.Button(control_buttons, text="Run Analysis", 
                                    command=self.calculate_analysis, width=25)
        self.btn_analyze.pack(side="left", padx=5)
        
        self.btn_settings = ttk.Button(control_buttons, text="Settings", 
                                     command=self.show_settings, width=15)
        self.btn_settings.pack(side="right", padx=5)

        self.games = []
        self.moves = []
        self.idx   = 0
        self.board = None
        self.eval_history = None

        self.load_game_list()
        if self.games:
            self.listbox.selection_set(0)
            self.on_game_select(None)

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        if self.engine: # Check if engine was successfully initialized
            self.engine.quit()
        self.destroy()

    def load_game_list(self, username=None):
        username = username or USER
        self.current_user = username # Keep current_user updated for ELO plot context
        self.listbox.delete(0, tk.END)
        self.games.clear()
        self.original_colors.clear() # Clear original colors as list is repopulated

        if username == USER:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            # Removed player_analysis from SELECT as it's no longer used for T-scores
            cur.execute("SELECT url, pgn, white, black, end_time FROM games ORDER BY end_time DESC")
            rows = cur.fetchall()
            conn.close()
        else:
            from fetch_games import fetch_current_month_games
            rows = []
            batch = fetch_current_month_games(username)
            for g in batch:
                rows.append((g["url"], g["pgn"], g["white"], g["black"], g["end_time"]))

        for i, (url, pgn, white, black, _) in enumerate(rows):
            self._insert_colored(i, url, pgn, white, black)

        self.btn_back.config(state="normal" if self.history else "disabled")

    def _insert_colored(self, idx, url, pgn, white, black):
        m = re.search(r'\[Result\s+"([^"]+)"\]', pgn)
        result = m.group(1) if m else "1/2-1/2"
        
        # white_elo_match = re.search(r'\\[WhiteElo\\s+"([^"]+)"\\]', pgn)
        # black_elo_match = re.search(r'\\[BlackElo\\s+"([^"]+)"\\]', pgn)
        white_elo_match = re.search(r'\[WhiteElo\s+"([^"]+)"\]', pgn)
        black_elo_match = re.search(r'\[BlackElo\s+"([^"]+)"\]', pgn)
        white_elo = white_elo_match.group(1) if white_elo_match else "?"
        black_elo = black_elo_match.group(1) if black_elo_match else "?"
        
        current_user_elo = "?"
        # Determine current user's ELO for display in listbox, handle potential case differences
        if white.lower() == self.current_user.lower():
            current_user_elo = white_elo
        elif black.lower() == self.current_user.lower():
            current_user_elo = black_elo

        if white.lower() == self.current_user.lower(): # Use lower for comparison
            if result == "1-0":   bg = COLORS["win_white"]
            elif result == "0-1": bg = COLORS["loss_white"]
            else:                 bg = COLORS["draw"]
        elif black.lower() == self.current_user.lower(): # Use lower for comparison
            if result == "0-1":   bg = COLORS["win_black"]
            elif result == "1-0": bg = COLORS["loss_black"]
            else:                 bg = COLORS["draw"]
        else: # Game does not involve current_user, use a neutral color or default
            bg = COLORS["draw"]


        label = f"{white} vs {black}  ({result})  [{self.current_user}: {current_user_elo}]"
        self.listbox.insert(tk.END, label)
        self.listbox.itemconfig(idx, {'bg': bg})
        self.original_colors[idx] = bg
        self.games.append((url, pgn))

    def calculate_stockfish_scores(self, game, depth=10):
        scores = []
        is_mate = []
        board = game.board()
        
        current_player_color_for_pov = chess.WHITE # Default POV to White for scores
        # Determine if current_user is playing to set POV, otherwise default to White
        pgn_white = game.headers.get("White", "").lower()
        pgn_black = game.headers.get("Black", "").lower()
        current_user_lower = self.current_user.lower()

        if pgn_white == current_user_lower:
            current_player_color_for_pov = chess.WHITE
        elif pgn_black == current_user_lower:
            current_player_color_for_pov = chess.BLACK
        
        total_positions = 1 + len(list(game.mainline_moves()))
        
        info = self.engine.analyse(board, chess.engine.Limit(depth=depth))
        score_obj = info["score"].pov(current_player_color_for_pov)
        if score_obj.is_mate():
            is_mate.append(True)
            scores.append(score_obj.score(mate_score=10)) # Use a larger mate score
        else:
            is_mate.append(False)
            scores.append(score_obj.score() / 100 if score_obj.score() is not None else 0)
        
        self.after(0, self.update_eval_progress, 1, total_positions)
        
        for i, move in enumerate(game.mainline_moves(), 2):
            board.push(move)
            info = self.engine.analyse(board, chess.engine.Limit(depth=depth))
            score_obj = info["score"].pov(current_player_color_for_pov)
            if score_obj.is_mate():
                is_mate.append(True)
                scores.append(score_obj.score(mate_score=10)) # Use a larger mate score
            else:
                is_mate.append(False)
                scores.append(score_obj.score() / 100 if score_obj.score() is not None else 0)
            
            self.after(0, self.update_eval_progress, i, total_positions)
        
        return scores, is_mate

    def calculate_wdl_probabilities(self, game, depth=10):
        wdl_probs = []
        board = game.board()
        
        current_player_color_for_pov = chess.WHITE # Default POV
        pgn_white = game.headers.get("White", "").lower()
        pgn_black = game.headers.get("Black", "").lower()
        current_user_lower = self.current_user.lower()

        if pgn_white == current_user_lower:
            current_player_color_for_pov = chess.WHITE
        elif pgn_black == current_user_lower:
            current_player_color_for_pov = chess.BLACK
        
        info = self.engine.analyse(board, chess.engine.Limit(depth=depth))
        wdl = info["score"].pov(current_player_color_for_pov).wdl()
        wdl_probs.append((wdl.wins / 1000.0, wdl.draws / 1000.0, wdl.losses / 1000.0))
        
        for move in game.mainline_moves():
            board.push(move)
            info = self.engine.analyse(board, chess.engine.Limit(depth=depth))
            wdl = info["score"].pov(current_player_color_for_pov).wdl()
            wdl_probs.append((wdl.wins / 1000.0, wdl.draws / 1000.0, wdl.losses / 1000.0))
        
        return wdl_probs

    def update_plot(self):
        self.ax1.clear()
        self.ax2.clear()
        
        if self.eval_history:
            scores, is_mate = self.eval_history
            
            total_segments = []
            total_scores = []
            mate_segments = []
            mate_scores = []

            for i, (score_val, mate_val) in enumerate(zip(scores, is_mate)):
                total_segments.append(i)
                total_scores.append(score_val)
                if mate_val:
                    mate_segments.append(i)
                    mate_scores.append(score_val) # Mate score already adjusted

            self.ax1.plot(total_segments, total_scores, 'b', alpha=0.7, linewidth=2, label='Evaluation (cp)')
            if mate_segments: # Only plot if there are mate scores
                 self.ax1.plot(mate_segments, mate_scores, 'ro', alpha=0.7, markersize=5, linestyle='None', label='Mate Score') # Red dots for mate

            if self.idx < len(scores):
                self.ax1.plot(self.idx, scores[self.idx], 'go', label='Current Position', markersize=8)
            
            self.ax1.axhline(y=0, color='k', linestyle='--', alpha=0.3)
            self.ax1.set_ylabel('Advantage (centipawns)')
            self.ax1.set_title('Game Evaluation')
            self.ax1.set_xticks([])
            self.ax1.grid(True, alpha=0.3)
            self.ax1.legend()

            if hasattr(self, 'wdl_history') and self.wdl_history:
                moves_wdl = range(len(self.wdl_history))
                wins = [w for w, _, _ in self.wdl_history]
                draws = [d for _, d, _ in self.wdl_history]
                losses = [l for _, _, l in self.wdl_history]
                
                self.ax2.plot(moves_wdl, wins, 'g-', alpha=0.7, label='Win %')
                self.ax2.plot(moves_wdl, draws, 'y-', alpha=0.7, label='Draw %')
                self.ax2.plot(moves_wdl, losses, 'r-', alpha=0.7, label='Loss %')
                
                if self.idx < len(wins): # Ensure index is valid for WDL plot
                    self.ax2.plot(self.idx, wins[self.idx], 'go', markersize=8) # No duplicate label
                
                self.ax2.set_xlabel('Move Number (ply)')
                self.ax2.set_ylabel('Probability')
                self.ax2.grid(True, alpha=0.3)
                self.ax2.legend()
                self.ax2.set_ylim(0, 1.1) # Ensure y-axis is between 0 and 1.1
        
        self.fig.tight_layout()
        self.canvas.draw()

    def on_slider_change(self, value):
        target_idx = int(float(value))
        if target_idx != self.idx:
            self.board = chess.Board() # Start from initial position
            # Push moves up to the target index
            for i in range(target_idx):
                if i < len(self.moves):
                    self.board.push(self.moves[i])
            self.idx = target_idx # Set current index correctly
            self._render_board()
            self.update_plot()

    def on_game_select(self, _):
        sel = self.listbox.curselection()
        if not sel:
            return
        url, pgn = self.games[sel[0]]
        print(f"Selected game with URL: {url}")

        for i in range(self.listbox.size()):
            if i in self.original_colors:
                self.listbox.itemconfig(i, {'bg': self.original_colors[i]})
        self.listbox.itemconfig(sel[0], {'bg': 'yellow'})

        tags = dict(re.findall(r'\[(\w+)\s+\"([^\"]*)\"\]', pgn))
        pgn_white_name = tags.get("White", "").strip()
        pgn_black_name = tags.get("Black", "").strip()
        pgn_white_elo  = tags.get("WhiteElo", "?")
        pgn_black_elo  = tags.get("BlackElo", "?")
        result     = tags.get("Result", "1/2-1/2")
        termination = tags.get("Termination", "Unknown") # Default to "Unknown" if not present

        # Store for potential later use, though self.players_label is primary now
        self.game_white_player = pgn_white_name 
        self.game_black_player = pgn_black_name

        self.selected_game_pgn = pgn
        self.selected_game_url = url
        self.selected_game_white_player_name = pgn_white_name
        self.selected_game_black_player_name = pgn_black_name
        
        # Determine detailed result strings for each player based on game result and termination
        white_player_final_result = ""
        black_player_final_result = ""

        if result == "1-0":
            white_player_final_result = f"Win"
            black_player_final_result = f"Loss"
        elif result == "0-1":
            white_player_final_result = f"Loss"
            black_player_final_result = f"Win"
        else: # Draw or other results like '*'
            # For draws, termination might be "Stalemate", "Agreement", "Repetition", etc.
            # If result is '*' (unterminated/unknown), termination might also be less specific.
            if result == "1/2-1/2":
                 white_player_final_result = f"Draw"
                 black_player_final_result = f"Draw"
            else: # Handles '*', etc.
                 white_player_final_result = f"Result: {termination}"
                 black_player_final_result = f"Result: {termination}"


        # Prepare player detail strings, prioritizing the current_user
        player1_display_details = ""
        player2_display_details = ""
        current_user_lower = self.current_user.lower()

        if pgn_white_name.lower() == current_user_lower:
            player1_display_details = f"{current_user_lower} - {pgn_white_elo} (White)"
            player2_display_details = f"{pgn_black_name} - {pgn_black_elo} (Black)"
            # print(f"Player 1: {player1_display_details}")
            # print(f"Player 2: {player2_display_details}")
        elif pgn_black_name.lower() == current_user_lower:
            player1_display_details = f"{current_user_lower} - {pgn_black_elo} (Black)"
            player2_display_details = f"{pgn_white_name} - {pgn_white_elo} (White)"
       
            print(f"Player 1: {player1_display_details}")
            print(f"Player 2: {player2_display_details}")
        else: 
            # Fallback if current_user is not playing (e.g., viewing a game from a different source not filtered)
            # Or if names have subtle mismatches not caught by .lower().strip()
            print(f"[WARN] Current user '{self.current_user}' not matched with PGN players '{pgn_white_name}', '{pgn_black_name}'. Displaying White first.")
            player1_display_details = f"{pgn_white_name} (White, Elo: {pgn_white_elo}) - {white_player_final_result}"
            player2_display_details = f"{pgn_black_name} (Black, Elo: {pgn_black_elo}) - {black_player_final_result}"
            
        # self.players_label.config(text=f"{player1_display_details} vs {player2_display_details} \n {termination}")
        # Assume player1_display_details and player2_display_details are strings
        line_above = f"{player1_display_details.capitalize()} vs {player2_display_details.capitalize()}"
        termination_centered = termination.center(len(line_above))

        self.players_label.config(text=f"{line_above}\n{termination_centered}")
        # Load evaluation data from DB if available
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        # Removed player_analysis from select as it's no longer used for T-scores here
        cur.execute("SELECT evaluation_data FROM games WHERE url = ?", (url,))
        row = cur.fetchone()
        conn.close()
        
        eval_data_str = row[0] if row and row[0] else None # Renamed to avoid conflict
        
        if eval_data_str:
            try:
                eval_data = json.loads(eval_data_str)
                self.eval_history = (eval_data['scores'], eval_data['is_mate'])
                if 'wdl_probs' in eval_data: # Check if wdl_probs exists
                    self.wdl_history = eval_data['wdl_probs']
                else:
                    self.wdl_history = None # Ensure it's None if not in data
                self.update_plot()
            except Exception as e:
                print(f"Error loading evaluation data: {e}")
                self.eval_history = None
                self.wdl_history = None
        else:
            self.eval_history = None
            self.wdl_history = None
            self.ax1.clear()
            self.ax2.clear()
            self.ax1.text(0.5, 0.5, "No evaluation data available.\nClick 'Calculate Analysis' to analyze.", 
                        ha='center', va='center', transform=self.ax1.transAxes)
            self.canvas.draw()

        game_obj = chess.pgn.read_game(io.StringIO(pgn)) # Renamed to avoid conflict
        self.moves = [n.move for n in game_obj.mainline()]
        
        self.turn_slider.config(to=len(self.moves)) # Slider is 0 to num_moves
        
        if result == "1-0":
            white_result = "Win"
            black_result = "Loss"
            if termination in ["checkmate", "time"]: white_result = f"Win ({termination})"
            elif termination in ["abandoned", "resignation"]: black_result = f"Loss)"
        elif result == "0-1":
            white_result = "Loss"
            black_result = "Win"
            if termination in ["checkmate", "time"]: black_result = f"Win ({termination})"
            elif termination in ["abandoned", "resignation"]: white_result = f"Loss)"
        else:
            white_result = "Draw"
            black_result = "Draw"
        
        # self.players_label.config(text=f"{pgn_white_name} (White, Elo: {pgn_white_elo}) vs {pgn_black_name} (Black, Elo: {pgn_black_elo}) {white_result} vs {black_result}")

        self.board = game_obj.board()
        self.idx = 0
        self.turn_slider.set(0)
        self._render_board()
        # Update ELO plot if view is player analysis
        if self.analysis_type.get() == "player":
            self.plot_elo_history(self.current_user, self.player_elo_ax, self.current_user)
            self.player_elo_fig.tight_layout()
            self.player_elo_canvas.draw()


    def _render_board(self):
        svg_data = chess.svg.board(board=self.board, size=700)
        # Convert SVG data to PNG using svglib and ReportLab
        drawing = svg2rlg(io.StringIO(svg_data)) # svglib expects a file-like object
        png_data = renderPM.drawToString(drawing, fmt="PNG")
        img = Image.open(io.BytesIO(png_data))
        self.photo = ImageTk.PhotoImage(img)
        self.board_label.config(image=self.photo)

    def go_next(self):
        if self.idx < len(self.moves):
            self.board.push(self.moves[self.idx])
            self.idx += 1
            self.turn_slider.set(self.idx)
            self._render_board()
            if self.analysis_type.get() == "evaluation": self.update_plot()

    def go_prev(self):
        if self.idx > 0:
            self.board.pop()
            self.idx -= 1
            self.turn_slider.set(self.idx)
            self._render_board()
            if self.analysis_type.get() == "evaluation": self.update_plot()

    def go_start(self):
        while self.idx > 0:
            self.board.pop()
            self.idx -= 1
        self.turn_slider.set(0)
        self._render_board()
        if self.analysis_type.get() == "evaluation": self.update_plot()

    def go_end(self):
        while self.idx < len(self.moves):
            self.board.push(self.moves[self.idx])
            self.idx += 1
        self.turn_slider.set(self.idx)
        self._render_board()
        if self.analysis_type.get() == "evaluation": self.update_plot()

    def show_back(self):
        if self.history: # Check if history is not empty
            prev = self.history.pop()
            self.load_game_list(prev)

    def _get_analysis_depth(self): # Retained for Stockfish evaluation depth
        """Handles the depth input dialog and saves the chosen depth."""
        # Use a different key for eval depth to not conflict if T-score depth was stored
        depth = simpledialog.askinteger("Analysis Depth",
                                      "Enter analysis depth for Stockfish evaluation (1-30):",
                                      minvalue=1, maxvalue=30,
                                      initialvalue=self.settings.get('last_eval_analysis_depth', 10))
        if depth is not None:
            self.settings['last_eval_analysis_depth'] = depth
            try:
                with open('settings.json', 'w') as f:
                    json.dump(self.settings, f, indent=4)
            except Exception as e:
                print(f"Error saving last eval analysis depth to settings: {e}")
        return depth

    # def show_player_analysis(self):
    #     # This function is called when "Calculate Analysis" is pressed in "Player Analysis" view.
    #     # Since T-Scores are removed, this button doesn't have a specific calculation to trigger
    #     # for the player view beyond what's automatically shown (ELO).
    #     # We can leave it as a no-op or log a message.
    #     print("[INFO] Player Analysis view selected. ELO History is displayed. No further calculations triggered by this button for this view.")
    #     # Optionally, could re-ensure ELO plot is up-to-date, though switch_analysis_view and on_game_select handle it.
    #     # self.plot_elo_history(self.current_user, self.player_elo_ax, f"{self.current_user}'s ELO")
    #     # self.player_elo_fig.tight_layout()
    #     # self.player_elo_canvas.draw()


    def plot_elo_history(self, username, ax, title_prefix=""):
        title_prefix = title_prefix.capitalize().split(" ")[0]+" ELO Record"
        ax.clear() # Clear the axes before plotting

        reset_sliders_to_full_range = (self._current_elo_plot_user != username)
        if self._current_elo_plot_user != username:
            self.time_control_vars.clear()
            self.time_control_colors.clear() # Clear colors when user changes

        if self._current_elo_plot_user == username and self._cached_processed_games_for_user:
            print(f"Using cached ELO data for {username}")
            processed_games = self._cached_processed_games_for_user
        else:
            print(f"Fetching ELO data for {username} from DB")
            print(DB_FILE)
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute(""" 
                SELECT end_time, pgn, white, black
                FROM games 
                WHERE LOWER(white) = ? OR LOWER(black) = ?
                ORDER BY end_time
            """, (username.lower(), username.lower()))
            rows = cur.fetchall()
            conn.close()
            
            if not rows:
                ax.text(0.5, 0.5, f"No ELO history available for {username}", 
                       ha='center', va='center', transform=ax.transAxes)
                ax.set_title(f"{title_prefix}")
                self.elo_start_slider.config(state="disabled", from_=1, to=1, value=1)
                self.elo_end_slider.config(state="disabled", from_=1, to=1, value=1)
                for widget in self.elo_time_control_filter_frame.winfo_children():
                    widget.destroy()
                self.time_control_vars.clear()
                self.time_control_colors.clear() # Also clear here
                self._current_elo_plot_user = username
                self._cached_processed_games_for_user = []
                self.player_elo_canvas.draw()
                return
            
            fetched_games_data = []
            for row_data in rows:
                timestamp_val = row_data[0]
                date = None
                try:
                    if isinstance(timestamp_val, str):
                        try:
                            timestamp_val = float(timestamp_val)
                        except ValueError:
                            continue
                    elif timestamp_val is None:
                        continue
                    if not isinstance(timestamp_val, (int, float)):
                        continue
                    date = datetime.datetime.fromtimestamp(timestamp_val)
                except Exception:
                    continue 
                
                pgn_text = row_data[1]
                game_white_player_name = row_data[2]
                game_black_player_name = row_data[3]
                tags = dict(re.findall(r'\[(\w+)\s+\"([^\"]*)\"\]', pgn_text))
                time_control = tags.get("TimeControl", "Unknown")
                white_elo_match = re.search(r'\[WhiteElo\s+"([^"]+)"\]', pgn_text)
                black_elo_match = re.search(r'\[BlackElo\s+"([^"]+)"\]', pgn_text)
                current_elo_value = None
                try:
                    if game_white_player_name.lower() == username.lower():
                        if white_elo_match and white_elo_match.group(1).isdigit():
                            current_elo_value = int(white_elo_match.group(1))
                    elif game_black_player_name.lower() == username.lower():
                        if black_elo_match and black_elo_match.group(1).isdigit():
                            current_elo_value = int(black_elo_match.group(1))
                except ValueError:
                    continue
                if current_elo_value is not None and date is not None:
                    fetched_games_data.append({'date': date, 'elo': current_elo_value, 'time_control': time_control})
            
            if not fetched_games_data:
                ax.text(0.5, 0.5, f"No valid ELO data found for {username}", 
                       ha='center', va='center', transform=ax.transAxes)
                ax.set_title(f"{title_prefix}")
                self.elo_start_slider.config(state="disabled", from_=1, to=1, value=1)
                self.elo_end_slider.config(state="disabled", from_=1, to=1, value=1)
                for widget in self.elo_time_control_filter_frame.winfo_children():
                    widget.destroy()
                self.time_control_vars.clear()
                self.time_control_colors.clear() # And here
                self._current_elo_plot_user = username
                self._cached_processed_games_for_user = []
                self.player_elo_canvas.draw()
                return

            self._current_elo_plot_user = username
            self._cached_processed_games_for_user = sorted(fetched_games_data, key=lambda g: g['date'])
            processed_games = self._cached_processed_games_for_user
            reset_sliders_to_full_range = True

        for widget in self.elo_time_control_filter_frame.winfo_children():
            widget.destroy()
        
        all_time_controls = sorted(list(set(g['time_control'] for g in processed_games))) if processed_games else []
        
        # Assign colors to time controls if not already assigned
        # Use a predefined list of colors from a colormap for consistency
        # We get the colors from the map once, and assign them cyclically.
        # This ensures that even if the number of time controls is > 10, we get colors.
        cmap_colors = plt.cm.get_cmap('tab10').colors 
        num_cmap_colors = len(cmap_colors)
        assigned_color_idx = len(self.time_control_colors) # Start assigning from next available index

        for tc in all_time_controls:
            if tc not in self.time_control_colors:
                self.time_control_colors[tc] = cmap_colors[assigned_color_idx % num_cmap_colors]
                assigned_color_idx += 1

        if not all_time_controls:
            ttk.Label(self.elo_time_control_filter_frame, text="No time control data available.").pack()
        else:
            current_tcs_vars = {}
            for tc in all_time_controls:
                if tc not in self.time_control_vars:
                    self.time_control_vars[tc] = tk.BooleanVar(value=True)
                current_tcs_vars[tc] = self.time_control_vars[tc]
                cb = ttk.Checkbutton(self.elo_time_control_filter_frame, text=tc, 
                                     variable=self.time_control_vars[tc],
                                     command=self._on_time_control_filter_change)
                cb.pack(side="left", padx=2, pady=2)
            self.time_control_vars = current_tcs_vars

        num_total_games = len(processed_games)
        if num_total_games < 1:
            ax.text(0.5, 0.5, f"ELO History for {username}\n(Not enough data)", ha='center', va='center', transform=ax.transAxes)
            ax.set_title(f"{title_prefix}")
            self.elo_start_slider.config(state="disabled", from_=1, to=max(1, num_total_games), value=1)
            self.elo_end_slider.config(state="disabled", from_=1, to=max(1, num_total_games), value=max(1, num_total_games))
            self.player_elo_canvas.draw()
            return
        else:
            self.elo_start_slider.config(state="normal", from_=1, to=num_total_games)
            self.elo_end_slider.config(state="normal", from_=1, to=num_total_games)

        if reset_sliders_to_full_range:
            self.elo_start_slider.set(1)
            self.elo_end_slider.set(num_total_games)
        
        start_val = int(self.elo_start_slider.get()) 
        end_val = int(self.elo_end_slider.get())
        if start_val > end_val:
            start_val = end_val 
            self.elo_start_slider.set(start_val)

        start_index = max(0, start_val - 1)
        end_index = min(num_total_games, end_val)
        games_in_range_unfiltered_tc = processed_games[start_index:end_index]

        games_in_range = [
            game for game in games_in_range_unfiltered_tc 
            if self.time_control_vars.get(game['time_control']) and self.time_control_vars[game['time_control']].get()
        ]

        if not games_in_range:
            ax.text(0.5, 0.5, f"No ELO data in selected range/filters for {username}", 
                       ha='center', va='center', transform=ax.transAxes)
        else:
            games_by_time_control = {}
            for game in games_in_range:
                tc = game['time_control']
                if tc not in games_by_time_control:
                    games_by_time_control[tc] = []
                games_by_time_control[tc].append(game)

            # No need for tc_colors = plt.cm.get_cmap(...) here anymore or color_idx
            plotted_something = False
            for tc, tc_games in games_by_time_control.items():
                if not tc_games: continue
                tc_games_sorted = sorted(tc_games, key=lambda g: g['date'])
                dates_to_plot = [g['date'] for g in tc_games_sorted]
                elos_to_plot = [g['elo'] for g in tc_games_sorted]
                if dates_to_plot:
                    # Use the pre-assigned color for this time control
                    color_to_use = self.time_control_colors.get(tc, 'black') # Default to black if somehow not found
                    ax.plot(dates_to_plot, elos_to_plot, marker='o', linestyle='-', linewidth=1, markersize=3, label=f"{tc} (Rating)", color=color_to_use)
                    plotted_something = True # Track if any line is plotted
            
            if plotted_something: 
                ax.legend(loc='best', fontsize='small')
            else:
                 ax.text(0.5, 0.5, f"No ELO data for selected time controls in range [{start_val}-{end_val}]", 
                       ha='center', va='center', transform=ax.transAxes)
            
            ax.text(0.02, 0.98, f"Displaying games: {start_val}-{end_val} of {num_total_games} total (across all TCs)", 
                    transform=ax.transAxes, va='top',
                    bbox=dict(facecolor='white', alpha=0.8))
        
        ax.set_title(f"{title_prefix}")
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        self.player_elo_fig.tight_layout()
        self.player_elo_canvas.draw()


    def show_evaluation_analysis(self):
        sel = self.listbox.curselection()
        if not sel: return
        url, pgn = self.games[sel[0]]
        
        depth = self._get_analysis_depth() # Use the helper
        
        if depth is None:
            return
        
        self.show_evaluation_loading()
        
        import threading
        self.eval_thread = threading.Thread(target=self.run_evaluation_analysis, 
                                         args=(url, pgn, depth))
        self.eval_thread.start()

    def show_evaluation_loading(self):
        self.ax1.clear()
        self.ax2.clear()
        
        # Ensure existing loading_frame is removed if any (e.g. from previous calculation)
        for widget in self.plot_frame.winfo_children():
            if isinstance(widget, ttk.Frame) and hasattr(widget, '_is_loading_frame'):
                 widget.destroy()

        loading_frame = ttk.Frame(self.plot_frame)
        loading_frame._is_loading_frame = True # Mark it
        loading_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        ttk.Label(loading_frame, text="Calculating evaluation...").pack(pady=10)
        self.eval_progress = ttk.Progressbar(loading_frame, mode='determinate', maximum=100)
        self.eval_progress.pack(fill='x', padx=10, pady=5)
        self.eval_status = ttk.Label(loading_frame, text="Preparing analysis...")
        self.eval_status.pack(pady=5)
        
        self.canvas.draw()

    def update_eval_progress(self, current, total):
        if hasattr(self, 'eval_progress') and self.eval_progress.winfo_exists(): # Check if progress bar exists
            percentage = (current / total) * 100 if total > 0 else 0
            self.eval_progress['value'] = percentage
            if hasattr(self, 'eval_status') and self.eval_status.winfo_exists(): # Check if status label exists
                 self.eval_status.config(
                    text=f"Analyzing position {current}/{total} - {percentage:.1f}% complete"
                )
            self.update_idletasks() # Essential for UI updates during long tasks


    def run_evaluation_analysis(self, url, pgn, depth):
        game = chess.pgn.read_game(io.StringIO(pgn))
        scores, is_mate = self.calculate_stockfish_scores(game, depth)
        wdl_probs = self.calculate_wdl_probabilities(game, depth)
        
        eval_data = {
            'scores': scores, 'is_mate': is_mate, 'wdl_probs': wdl_probs, 'depth': depth
        }
        conn = None # Ensure conn is defined for finally block
        try:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("UPDATE games SET evaluation_data = ? WHERE url = ?",
                      (json.dumps(eval_data), url))
            conn.commit()
        except Exception as e:
            print(f"Error storing evaluation data: {e}")
        finally:
            if conn: conn.close()
        
        # Clear loading state widgets before updating plot
        self.after(0, self._clear_loading_widgets_and_update_plot, scores, is_mate, wdl_probs)

    def _clear_loading_widgets_and_update_plot(self, scores, is_mate, wdl_probs):
        for widget in self.plot_frame.winfo_children():
            if isinstance(widget, ttk.Frame) and hasattr(widget, '_is_loading_frame'):
                widget.destroy()
        
        self.eval_history = (scores, is_mate)
        self.wdl_history = wdl_probs
        self.update_plot()


    def show_top3_moves(self):
        if not self.board:
            return
        try:
            info = self.engine.analyse(self.board, chess.engine.Limit(depth=20), multipv=3) # Increased depth for better top moves
        except chess.engine.EngineTerminatedError:
            messagebox.showerror("Engine Error", "Stockfish engine terminated or not available.")
            return
        except Exception as e:
            messagebox.showerror("Analysis Error", f"Could not get top 3 moves: {e}")
            return

        arrows = []
        colors = ['green', 'blue', 'yellow']
        
        for i, pv_info in enumerate(info): # Iterate through PV info
            if i >= 3: break
            if "pv" in pv_info and pv_info["pv"]: # Check if 'pv' and move list exist
                move = pv_info["pv"][0]
                arrows.append(chess.svg.Arrow(tail=move.from_square, head=move.to_square, color=colors[i]))
            else: # Handle cases where a PV might be missing (e.g. mate in 0)
                print(f"Warning: PV {i+1} missing or empty in analysis info.")

        svg_data = chess.svg.board(board=self.board, size=700, arrows=arrows)
        # Convert SVG data to PNG using svglib and ReportLab
        drawing = svg2rlg(io.StringIO(svg_data)) # svglib expects a file-like object
        png_data = renderPM.drawToString(drawing, fmt="PNG")
        img = Image.open(io.BytesIO(png_data))
        self.photo = ImageTk.PhotoImage(img)
        self.board_label.config(image=self.photo)

    def load_settings(self):
        self.settings = {}
        print(os.getcwd())
        try:
            if os.path.exists(os.getcwd()+'/acco/resources/settings.json'):
                with open(os.getcwd()+'/acco/resources/settings.json', 'r') as f:
                    self.settings = json.load(f)
                    print(self.settings)
                    global USER, DB_FILE, STOCKFISH_PATH
                    USER = self.settings.get('username', USER) # Keep USER default if not in settings
                    STOCKFISH_PATH = self.settings.get('stockfish_path', STOCKFISH_PATH)
                    # Ensure DB_FILE is updated if USER changes or is loaded
                    if USER: # Only form DB_FILE if USER is not empty
                         DB_FILE = f"acco/resources/{USER.lower().replace(' ', '_')}_games.db" # Make DB name filesystem-friendly
                    else: # Handle case where username might be empty
                         DB_FILE = "acco/resources/default_games.db" 
                         print("Warning: Username is empty in settings, using default_games.db")
            else:
                print("It do not?")

        except Exception as e:
            print(f"Error loading settings: {e}")
            # Fallback if settings are corrupt or missing
            USER = USER or "Guest" # Ensure USER is not None
            DB_FILE = f"acco/resources/{USER.lower().replace(' ', '_')}_games.db"


    def show_settings(self):
        dialog = SettingsDialog(self)
        self.wait_window(dialog)
        old_db_file = DB_FILE
        self.load_settings()
        self.current_user = USER # Update current_user after loading settings

        # Refresh UI elements that depend on current_user
        self.player_frame.config(text=f"Analysis for {self.current_user}")
        
        # Check if username changed OR if games were updated in the settings dialog
        # The dialog will need to set a flag like `dialog.games_updated` if it performed an update.
        if old_db_file != DB_FILE or getattr(dialog, 'games_updated', False) or dialog.saved_settings:
            print("[SETTINGS] Username/DB changed, settings saved, or games updated.")
            # Reload game list for new user/DB or if games were updated
            self.load_game_list() 
            
            # Refresh ELO plot for the potentially new user or updated game list
            # Clear cached ELO data to force a re-fetch and re-process, including time controls and colors
            self._cached_processed_games_for_user = [] 
            self.time_control_vars.clear()
            self.time_control_colors.clear() # Also clear colors
            self.plot_elo_history(self.current_user, self.player_elo_ax, self.current_user)
            self.player_elo_fig.tight_layout()
            self.player_elo_canvas.draw()
            
            if self.listbox.size() > 0:
                self.listbox.selection_set(0)
                self.on_game_select(None)
            else: # Clear game specific details if no games
                self.players_label.config(text="")
                self.board_label.config(image=None) # Clear board
                # Clear eval history and plot
                self.eval_history = None
                self.wdl_history = None
                self.update_plot()


    def switch_analysis_view(self):
        if self.analysis_type.get() == "player":
            self.plot_frame.pack_forget()
            self.player_frame.pack(fill="both", expand=True)
            self.plot_elo_history(self.current_user, self.player_elo_ax, self.current_user)
            self.player_elo_fig.tight_layout()
            self.player_elo_canvas.draw()
        else: # "evaluation"
            self.player_frame.pack_forget()
            self.plot_frame.pack(fill="both", expand=True)
            if self.eval_history:
                self.update_plot()
            else: # If no eval history, show placeholder
                self.ax1.clear()
                self.ax2.clear()
                self.ax1.text(0.5, 0.5, "No evaluation data available.\\nSelect a game and click 'Calculate Analysis'.", 
                            ha='center', va='center', transform=self.ax1.transAxes)
                self.canvas.draw()

    def calculate_analysis(self):
        # if self.analysis_type.get() == "player":
        #     self.show_player_analysis() # Will now do very little
        # else: # "evaluation"
        self.show_evaluation_analysis()

    def on_elo_range_change(self, _value=None):
        # This method is called when either slider is moved.
        # It ensures start_val <= end_val and then triggers a replot.
        
        # Temporarily disable commands to prevent recursive calls if we .set() a slider
        original_start_cmd = self.elo_start_slider.cget("command")
        original_end_cmd = self.elo_end_slider.cget("command")
        self.elo_start_slider.config(command="")
        self.elo_end_slider.config(command="")

        start_val = int(self.elo_start_slider.get())
        end_val = int(self.elo_end_slider.get())
        
        num_points = len(self._cached_processed_games_for_user) # Max possible value for end_slider
        if num_points == 0: # Should not happen if sliders are active
            self.elo_start_slider.config(command=original_start_cmd)
            self.elo_end_slider.config(command=original_end_cmd)
            return

        # Ensure start_val is not greater than end_val
        if start_val > end_val:
            # Determine which slider was moved to cause the overlap
            # This requires knowing the previous value or which slider triggered the event.
            # For simplicity, if start > end, assume start slider was moved too far right OR end slider too far left.
            # If _value (tk gives slider value as string) can identify the source, that's better.
            # However, _value is just the new value, not which slider it came from.
            # Let's assume if start_val > end_val, we prioritize adjusting the one that makes range valid.
            # If we just check if this callback was triggered by start_slider or end_slider this would be easy
            # but Tkinter scale command doesn't pass that. 
            # A common approach: check which slider *could* have caused this. 
            # If self.elo_start_slider.get() caused start_val > end_val, then set end_val = start_val.
            # If self.elo_end_slider.get() caused end_val < start_val, then set start_val = end_val.
            # This can be tricky. A simpler cross-validation:
            self.elo_end_slider.set(start_val) # If start went past end, pull end to start
            end_val = start_val
        
        # After potential adjustment, re-check end_val compared to start_val
        # This handles the case where end_slider was moved to be less than start_slider
        if end_val < start_val:
            self.elo_start_slider.set(end_val) # If end went before start, pull start to end
            # start_val = end_val # Not needed as plot_elo_history will re-read

        # Restore commands
        self.elo_start_slider.config(command=original_start_cmd)
        self.elo_end_slider.config(command=original_end_cmd)

        if self._current_elo_plot_user:
            self.plot_elo_history(self._current_elo_plot_user, self.player_elo_ax, self._current_elo_plot_user)

    def _on_time_control_filter_change(self):
        # This method is called when a time control filter checkbox is changed.
        # It will re-trigger the plotting of ELO history with the new filter settings.
        if self._current_elo_plot_user:
            self.plot_elo_history(self._current_elo_plot_user, self.player_elo_ax, self._current_elo_plot_user)


if __name__ == "__main__":
    app = GameViewer()
    app.mainloop()

