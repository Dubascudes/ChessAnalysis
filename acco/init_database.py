from .fetch_games import fetch_month_pgn, parse_pgn_games, fetch_current_month_games_and_save_to_db, fetch_current_month_games


#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import os

def main():
    # locate settings.json next to this script
    settings_path = Path(__file__).parent / "resources/settings.json"
    if not settings_path.is_file():
        print(f"Error: could not find {settings_path}")
        sys.exit(1)

    # load existing settings
    with open(settings_path, "r") as f:
        settings = json.load(f)

    # prompt for username
    current_user = settings.get("username", "")
    new_user = input(f"Enter username [{current_user}]: ").strip()
    if new_user:
        settings["username"] = new_user

    # prompt for stockfish path
    current_path = settings.get("stockfish_path", "")
    new_path = input(f"Enter Stockfish executable path [{current_path}]: ").strip()
    if new_path:
        settings["stockfish_path"] = new_path

    # write back updated settings
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=4)

    # initialize games db:
    fetch_current_month_games_and_save_to_db(settings["username"], "acco/resources/"+settings["username"]+"_games.db")
    print("✅ settings.json updated successfully.")

if __name__ == "__main__":
    main()
