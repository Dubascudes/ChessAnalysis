#!/usr/bin/env python3
"""
fetch_games.py

Downloads the current month's PGN batch from Chess.com for user deepcroaker,
stores the full PGN (tags + moves) in an SQLite DB, and migrates schema as needed.
"""
import sqlite3
import requests
import re
from datetime import datetime, timezone
from urllib.parse import quote

DB_FILE = "magnuscarlsen_games.db"
USERNAME = "magnuscarlsen"  # API path is case-sensitive; use lowercase here
API_URL_TEMPLATE = (
    "https://api.chess.com/pub/player/{username}/games/{year}/{month:02d}/pgn"
)
DEFAULT_USER = "magnuscarlsen"

# A proper User-Agent and Accept header to avoid 403
HEADERS = {
    "User-Agent": "acco/1.0 (will.english@ufl.edu)",
    "Accept": "application/x-chess-pgn",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://api.chess.com"
}

def ensure_db(conn):
    """Create the games table (if missing) and migrate schema for time_control."""
    cur = conn.cursor()
    # base schema (tags + moves stored in pgn)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            url TEXT PRIMARY KEY,
            pgn TEXT,
            end_time INTEGER,
            white TEXT,
            black TEXT
        )
        """
    )
    # check for time_control column
    cur.execute("PRAGMA table_info(games)")
    existing = {row[1] for row in cur.fetchall()}
    if "time_control" not in existing:
        cur.execute("ALTER TABLE games ADD COLUMN time_control TEXT")
    conn.commit()


# def fetch_month_pgn(username: str, year: int, month: int) -> str:
#     url = API_URL_TEMPLATE.format(username=username, year=year, month=month)
#     resp = requests.get(url, headers=HEADERS)
#     resp.raise_for_status()
#     return resp.text


# def parse_pgn_games(raw_text):
#     """
#     Split the raw PGN batch into individual full-game entries (tags+moves).
#     Returns a list of dicts with keys: url, pgn, end_time, white, black, time_control.
#     """
#     # split at each '[Event' tag, preserving it
#     entries = re.split(r"(?=\[Event)", raw_text.strip())
#     games = []
#     for entry in entries:
#         entry = entry.strip()
#         if not entry:
#             continue
#         # parse tags block
#         tags = dict(re.findall(r"\[(\w+)\s+\"([^\"]*)\"\]", entry))
#         # fallback for date/time
#         date = tags.get("EndDate") or tags.get("UTCDate") or tags.get("Date")
#         time_str = tags.get("EndTime") or tags.get("UTCTime") or tags.get("StartTime")
#         if not date or not time_str:
#             # skip entries missing timestamp
#             continue
#         # parse into UNIX timestamp (UTC)
#         try:
#             dt = datetime.strptime(f"{date} {time_str}", "%Y.%m.%d %H:%M:%S")
#         except ValueError:
#             continue
#         ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
#         games.append({
#             "url": tags.get("Link", ""),
#             "pgn": entry,
#             "end_time": ts,
#             "white": tags.get("White", ""),
#             "black": tags.get("Black", ""),
#             "time_control": tags.get("TimeControl", "")
#         })
#     return games


def update_database():
    # current UTC year/month
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    print(f"Downloading PGNs for {year}-{month:02d}…")
    raw = fetch_month_pgn(year, month)
    games = parse_pgn_games(raw)

    conn = sqlite3.connect(DB_FILE)
    ensure_db(conn)
    cur = conn.cursor()

    new_count = 0
    for g in games:
        cur.execute(
            """
            INSERT OR IGNORE INTO games
              (url, pgn, end_time, white, black, time_control)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (g["url"], g["pgn"], g["end_time"], g["white"], g["black"], g["time_control"])
        )
        if cur.rowcount:
            new_count += 1
    conn.commit()
    conn.close()

    print(f"Processed {len(games)} games; inserted {new_count} new records.")


def fetch_month_pgn(username: str, year: int, month: int) -> str:
    url = API_URL_TEMPLATE.format(username=username, year=year, month=month)
    print(url)
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.text



def parse_pgn_games(raw_pgn_text: str) -> list[dict]:
    # split on each "[Event" so tags+moves stay together
    blocks = raw_pgn_text.split("\n\n[Event")
    games = []
    for i, blk in enumerate(blocks):
        if i > 0:
            blk = "[Event" + blk
        pgn = blk.strip()
        # pull tags
        tags = dict(re.findall(r'\[(\w+)\s+"([^"]*)"\]', pgn))
        # extract timestamp
        date     = tags.get("EndDate") or tags.get("UTCDate") or tags.get("Date", "")
        time_str = tags.get("EndTime") or tags.get("UTCTime") or tags.get("StartTime", "")
        try:
            dt = datetime.strptime(f"{date} {time_str}", "%Y.%m.%d %H:%M:%S")
            end_ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            end_ts = 0
        games.append({
            "url":          tags.get("Link", ""),
            "pgn":          pgn,
            "end_time":     end_ts,
            "time_control": tags.get("TimeControl", ""),
            "white":        tags.get("White", ""),
            "black":        tags.get("Black", ""),
        })
    return games

def fetch_current_month_games(username: str = "magnuscarlsen") -> list[dict]:
    """
    Download & parse the current month's PGN batch
    for `username` (defaults to DEFAULT_USER).
    Returns a list of dicts with keys:
    url, pgn, end_time, time_control, white, black.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return parse_pgn_games(fetch_month_pgn(username, now.year, now.month))

def fetch_current_month_games_and_save_to_db(username: str, db_file_path: str) -> tuple[bool, str]:
    """Fetches current month's games for a user and saves them to the specified DB."""
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    
    print(f"Fetching PGNs for {username} for {year}-{month:02d} into {db_file_path}...")
    try:
        raw_pgn = fetch_month_pgn(username, year, month)
        if not raw_pgn.strip():
            return True, f"No games found for {username} for {year}-{month:02d}."
        
        games = parse_pgn_games(raw_pgn)
        if not games:
            return True, f"Parsed 0 games for {username} for {year}-{month:02d}."

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return True, f"No games available for {username} for {year}-{month:02d} (404 Not Found)."
        return False, f"HTTP error fetching games: {e}"
    except Exception as e:
        return False, f"Error fetching or parsing games: {e}"

    conn = None
    try:
        conn = sqlite3.connect(db_file_path)
        ensure_db(conn) # Ensure table and columns exist
        cur = conn.cursor()

        new_count = 0
        for g in games:
            # Ensure all expected keys are present, providing defaults if necessary
            # The `games` table now includes `evaluation_data` which might not be in `g`
            # For newly fetched games, evaluation_data will be NULL.
            cur.execute(
                """
                INSERT OR IGNORE INTO games
                  (url, pgn, end_time, white, black, time_control)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (g.get("url", ""), 
                 g.get("pgn", ""), 
                 g.get("end_time", 0), 
                 g.get("white", ""), 
                 g.get("black", ""), 
                 g.get("time_control", ""))
            )
            if cur.rowcount:
                new_count += 1
        conn.commit()
        return True, f"Processed {len(games)} games; inserted {new_count} new records into {db_file_path}."
    except Exception as e:
        return False, f"Database error for {db_file_path}: {e}"
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    update_database()
