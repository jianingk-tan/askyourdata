"""
init_db.py — Downloads the real Northwind SQLite database.

Source: https://github.com/jpwhite3/northwind-SQLite3 (MIT-licensed)
This is Microsoft's classic Northwind sample dataset, ported to SQLite.

Run once before launching the app:
    python scripts/init_db.py
"""

import sys
import urllib.request
from pathlib import Path

DB_URL = "https://github.com/jpwhite3/northwind-SQLite3/raw/main/dist/northwind.db"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "northwind.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _progress(block_num: int, block_size: int, total_size: int) -> None:
    """Simple download progress bar."""
    if total_size <= 0:
        return
    downloaded = block_num * block_size
    pct = min(100, downloaded * 100 // total_size)
    bar = "#" * (pct // 4) + "." * (25 - pct // 4)
    mb = downloaded / 1024 / 1024
    total_mb = total_size / 1024 / 1024
    sys.stdout.write(f"\r  [{bar}] {pct:3d}%  ({mb:.1f} / {total_mb:.1f} MB)")
    sys.stdout.flush()


def download_database() -> None:
    if DB_PATH.exists():
        size_mb = DB_PATH.stat().st_size / 1024 / 1024
        print(f"Database already exists at {DB_PATH} ({size_mb:.1f} MB)")
        print("Delete it manually if you want to re-download.")
        _print_summary()
        return

    print("Downloading Northwind database (~24 MB)...")
    print(f"  Source: {DB_URL}")
    print(f"  Target: {DB_PATH}")

    try:
        urllib.request.urlretrieve(DB_URL, DB_PATH, reporthook=_progress)
        print()  # newline after progress bar
    except Exception as exc:
        print(f"\nDownload failed: {exc}")
        print("\nIf you're behind a firewall, you can download manually:")
        print(f"  1. Open {DB_URL} in your browser")
        print(f"  2. Save the file as: {DB_PATH}")
        sys.exit(1)

    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    print(f"\nNorthwind database ready at: {DB_PATH} ({size_mb:.1f} MB)")
    _print_summary()


def _print_summary() -> None:
    """Show what's inside so the user knows the download worked."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    print("\nTables:")
    for (table_name,) in cur.fetchall():
        n = cur.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        print(f"   {table_name:<25} {n:>8,} rows")
    conn.close()


if __name__ == "__main__":
    download_database()
