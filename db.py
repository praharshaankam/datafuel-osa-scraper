"""SQLite schema and persistence helpers for the QuickMart OSA project."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("osa.db")

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS stores (
    store_id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    name TEXT NOT NULL,
    is_active INTEGER NOT NULL,
    is_serviceable INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sweeps (
    as_of_utc TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS store_sweeps (
    store_id TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    complete INTEGER NOT NULL,
    reason TEXT,
    item_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (store_id, as_of_utc),
    FOREIGN KEY (store_id) REFERENCES stores(store_id),
    FOREIGN KEY (as_of_utc) REFERENCES sweeps(as_of_utc)
);
CREATE TABLE IF NOT EXISTS inventory (
    store_id TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    name TEXT NOT NULL,
    in_stock INTEGER NOT NULL CHECK (in_stock IN (0,1)),
    qty INTEGER,
    price REAL,
    observed_at_utc TEXT NOT NULL,
    PRIMARY KEY (store_id, as_of_utc, sku_id),
    FOREIGN KEY (store_id, as_of_utc) REFERENCES store_sweeps(store_id, as_of_utc)
);
CREATE INDEX IF NOT EXISTS idx_stores_city ON stores(city, is_active);
CREATE INDEX IF NOT EXISTS idx_inventory_sku ON inventory(sku_id);
"""

def connect(path=DB_PATH):
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
