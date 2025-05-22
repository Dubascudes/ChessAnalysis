#!/usr/bin/env python3
"""
settings.py

Handles the settings dialog and settings management for the chess game viewer.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import glob
from datetime import datetime
import sqlite3
from fetch_games import fetch_month_pgn, parse_pgn_games

# Default values - will be updated from settings
USER = "deepcroaker"
DB_FILE = f"{USER.lower()}_games.db"

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("600x800")
        
        # Make dialog modal
        self.transient(parent)
        self.grab_set()
        
        # Load current settings
        self.load_settings()
        
        # Create main container
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill="both", expand=True)
        
        # Username settings
        username_frame = ttk.LabelFrame(main_frame, text="Username Settings", padding="5")
        username_frame.pack(fill="x", pady=5)
        
        ttk.Label(username_frame, text="Username:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.username_var = tk.StringVar(value=self.settings.get('username', USER))
        ttk.Entry(username_frame, textvariable=self.username_var).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        # Evaluation settings
        eval_frame = ttk.LabelFrame(main_frame, text="Evaluation Settings", padding="5")
        eval_frame.pack(fill="x", pady=5)
        
        ttk.Label(eval_frame, text="Default Evaluation Depth:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.depth_var = tk.IntVar(value=self.settings.get('default_depth', 10))
        ttk.Spinbox(eval_frame, from_=1, to=30, textvariable=self.depth_var, width=5).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        
        self.use_default_var = tk.BooleanVar(value=self.settings.get('use_default_depth', False))
        ttk.Checkbutton(eval_frame, text="Always use default evaluation depth", 
                       variable=self.use_default_var).grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w")
        
        # Database list
        db_frame = ttk.LabelFrame(main_frame, text="Available Databases", padding="5")
        db_frame.pack(fill="both", expand=True, pady=5)
        
        # Create treeview for databases
        columns = ("Database", "Size", "Last Modified")
        self.db_tree = ttk.Treeview(db_frame, columns=columns, show="headings", height=6)
        
        # Configure columns
        self.db_tree.heading("Database", text="Database")
        self.db_tree.heading("Size", text="Size")
        self.db_tree.heading("Last Modified", text="Last Modified")
        
        self.db_tree.column("Database", width=200)
        self.db_tree.column("Size", width=100)
        self.db_tree.column("Last Modified", width=200)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(db_frame, orient="vertical", command=self.db_tree.yview)
        self.db_tree.configure(yscrollcommand=scrollbar.set)
        
        # Pack treeview and scrollbar
        self.db_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Create context menu
        self.context_menu = tk.Menu(self.db_tree, tearoff=0)
        self.context_menu.add_command(label="Set as Current User", command=self.set_selected_as_user)
        
        # Bind right-click to show context menu
        self.db_tree.bind("<Button-3>", self.show_context_menu)
        
        # Populate database list
        self.populate_database_list()
        
        # Add new database section
        add_db_frame = ttk.LabelFrame(main_frame, text="Add New Database", padding="5")
        add_db_frame.pack(fill="x", pady=5)
        
        # Create a frame for the entry and button
        add_db_input_frame = ttk.Frame(add_db_frame)
        add_db_input_frame.pack(fill="x", padx=5, pady=5)
        
        # Username input
        ttk.Label(add_db_input_frame, text="Chess.com Username:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.new_username_var = tk.StringVar()
        ttk.Entry(add_db_input_frame, textvariable=self.new_username_var).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        # Date inputs
        ttk.Label(add_db_input_frame, text="Start Date (MM/YYYY):").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.start_date_var = tk.StringVar()
        ttk.Entry(add_db_input_frame, textvariable=self.start_date_var).grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        
        ttk.Label(add_db_input_frame, text="End Date (MM/YYYY):").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.end_date_var = tk.StringVar()
        ttk.Entry(add_db_input_frame, textvariable=self.end_date_var).grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        
        # Add status label
        self.add_db_status = ttk.Label(add_db_frame, text="")
        self.add_db_status.pack(pady=5)
        
        # Add progress bar (initially hidden)
        self.add_db_progress = ttk.Progressbar(add_db_frame, mode='determinate')
        
        # Add button
        ttk.Button(add_db_input_frame, text="Create Database", 
                  command=self.create_new_database).grid(row=3, column=0, columnspan=2, pady=10)
        
        # Configure grid weights
        add_db_input_frame.grid_columnconfigure(1, weight=1)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=10)
        
        ttk.Button(button_frame, text="Save", command=self.save_settings).pack(side="right", padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.destroy).pack(side="right", padx=5)
        
        # Store original window height
        self.original_height = 800
        
        # Center the dialog
        self.center_window()
    
    def center_window(self):
        """Center the dialog on the parent window"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')
    
    def load_settings(self):
        """Load settings from settings.json"""
        self.settings = {}
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r') as f:
                    self.settings = json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
    
    def save_settings(self):
        """Save settings to settings.json"""
        try:
            settings = {
                'username': self.username_var.get(),
                'default_depth': self.depth_var.get(),
                'use_default_depth': self.use_default_var.get()
            }
            with open('settings.json', 'w') as f:
                json.dump(settings, f, indent=4)
            
            # Update global variables
            global USER, DB_FILE
            USER = settings['username']
            DB_FILE = f"{USER.lower()}_games.db"
            
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")
    
    def populate_database_list(self):
        """Populate the database list with available .db files"""
        # Clear existing items
        for item in self.db_tree.get_children():
            self.db_tree.delete(item)
        
        # Find all .db files
        db_files = glob.glob("*_games.db")
        
        for db_file in db_files:
            try:
                # Get file stats
                stats = os.stat(db_file)
                size = stats.st_size
                modified = stats.st_mtime
                
                # Format size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size/1024:.1f} KB"
                else:
                    size_str = f"{size/(1024*1024):.1f} MB"
                
                # Format date
                date_str = datetime.fromtimestamp(modified).strftime('%Y-%m-%d %H:%M:%S')
                
                # Insert into treeview
                self.db_tree.insert("", "end", values=(db_file, size_str, date_str))
            except Exception as e:
                print(f"Error processing database {db_file}: {e}")
    
    def show_progress_bar(self):
        """Show the progress bar and adjust window height"""
        self.add_db_progress.pack(fill="x", padx=5, pady=5)
        # Increase window height by 100px
        current_width = self.winfo_width()
        self.geometry(f"{current_width}x{self.original_height + 100}")
        self.update_idletasks()

    def hide_progress_bar(self):
        """Hide the progress bar and restore window height"""
        self.add_db_progress.pack_forget()
        # Restore original window height
        current_width = self.winfo_width()
        self.geometry(f"{current_width}x{self.original_height}")
        self.update_idletasks()

    def create_new_database(self):
        """Create a new database for the given Chess.com username"""
        username = self.new_username_var.get().strip()
        start_date = self.start_date_var.get().strip()
        end_date = self.end_date_var.get().strip()
        
        # Validate inputs
        if not username:
            self.add_db_status.config(text="Please enter a username", foreground="red")
            return
            
        # Validate date format
        import re
        date_pattern = r'^(0[1-9]|1[0-2])/(\d{4})$'  # MM/YYYY format
        
        if not re.match(date_pattern, start_date):
            self.add_db_status.config(text="Start date must be in MM/YYYY format", foreground="red")
            return
            
        if not re.match(date_pattern, end_date):
            self.add_db_status.config(text="End date must be in MM/YYYY format", foreground="red")
            return
            
        # Parse dates
        start_month, start_year = map(int, start_date.split('/'))
        end_month, end_year = map(int, end_date.split('/'))
        
        # Validate date range
        if (end_year < start_year) or (end_year == start_year and end_month < start_month):
            self.add_db_status.config(text="End date must be after start date", foreground="red")
            return
        
        try:
            # Show progress bar
            self.show_progress_bar()
            
            # Create database
            db_file = f"{username.lower()}_games.db"
            conn = sqlite3.connect(db_file)
            cur = conn.cursor()
            
            # Create table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    url TEXT PRIMARY KEY,
                    pgn TEXT,
                    white TEXT,
                    black TEXT,
                    end_time TEXT,
                    cheating_analysis TEXT,
                    evaluation_data TEXT
                )
            """)
            
            # Initialize counters
            current_month = start_month
            current_year = start_year
            total_games = 0
            
            # Calculate total months to process
            total_months = (end_year - start_year) * 12 + (end_month - start_month + 1)
            months_processed = 0
            
            # Reset progress bar
            self.add_db_progress['value'] = 0
            self.add_db_progress['maximum'] = total_months
            
            # Fetch games month by month
            while (current_year < end_year) or (current_year == end_year and current_month <= end_month):
                # Update status
                status_text = f"Fetching games for {username} - {current_month:02d}/{current_year}"
                self.add_db_status.config(text=status_text, foreground="blue")
                self.update_idletasks()
                
                # Fetch games for current month
                raw_pgn = fetch_month_pgn(username, current_year, current_month)
                games = parse_pgn_games(raw_pgn)
                
                if games:
                    # Insert games
                    for game in games:
                        cur.execute("""
                            INSERT OR IGNORE INTO games (url, pgn, white, black, end_time)
                            VALUES (?, ?, ?, ?, ?)
                        """, (game["url"], game["pgn"], game["white"], game["black"], game["end_time"]))
                    total_games += len(games)
                
                # Update progress
                months_processed += 1
                self.add_db_progress['value'] = months_processed
                self.update_idletasks()
                
                # Move to next month
                current_month += 1
                if current_month > 12:
                    current_month = 1
                    current_year += 1
            
            conn.commit()
            conn.close()
            
            # Update status and clear input
            self.add_db_status.config(
                text=f"Successfully created database for {username} with {total_games} games", 
                foreground="green"
            )
            self.new_username_var.set("")
            self.start_date_var.set("")
            self.end_date_var.set("")
            
            # Hide progress bar
            self.hide_progress_bar()
            
            # Refresh database list
            self.populate_database_list()
            
            # Ensure the new database is visible in the list
            self.db_tree.see(self.db_tree.get_children()[-1])
            
        except Exception as e:
            self.add_db_status.config(text=f"Error: {str(e)}", foreground="red")
            print(f"Error creating database: {e}")
            # Hide progress bar on error
            self.hide_progress_bar() 

    def show_context_menu(self, event):
        """Show the context menu on right-click"""
        # Select the item under the cursor
        item = self.db_tree.identify_row(event.y)
        if item:
            # Select the item
            self.db_tree.selection_set(item)
            # Show the context menu
            self.context_menu.post(event.x_root, event.y_root)

    def set_selected_as_user(self):
        """Set the selected database's username as the current user"""
        selection = self.db_tree.selection()
        if not selection:
            return
            
        # Get the database filename from the selected item
        db_filename = self.db_tree.item(selection[0])['values'][0]
        
        # Extract username from filename (remove '_games.db')
        username = db_filename.replace('_games.db', '')
        
        # Update the username field
        self.username_var.set(username) 