"""Original AI-written review target with three focused safety fixes."""
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
import requests

PORTAL = "http://127.0.0.1:8765"
HEADERS = {"X-Api-Key": "dfhire-2026"}

def fetch_inventory(store_id, as_of, cursor="0", results=None):
    """Fetch pages with a timeout and bounded retries; results are per-call."""
    if results is None:
        results = []
    attempts = 0
    while attempts < 5:
        try:
            r = requests.get(f"{PORTAL}/v1/stores/{store_id}/inventory",
                             params={"as_of": as_of, "cursor": cursor},
                             headers=HEADERS, timeout=5)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", "2"))
                time.sleep(min(max(wait, 0), 30))
                attempts += 1
                continue
            if r.status_code in (500, 502, 503, 504):
                attempts += 1
                time.sleep(min(0.5 * 2 ** (attempts - 1), 8))
                continue
            r.raise_for_status()
            break
        except (requests.Timeout, requests.ConnectionError):
            attempts += 1
            time.sleep(min(0.5 * 2 ** (attempts - 1), 8))
    else:
        raise RuntimeError(f"inventory request failed after {attempts} attempts for {store_id}")
    body = r.json()
    results.extend(body["items"])
    if body.get("next_cursor") is not None:
        return fetch_inventory(store_id, as_of, str(body["next_cursor"]), results)
    return results

def save(conn, store_id, items):
    for it in items:
        conn.execute("""INSERT INTO inventory
            (store_id, sku_id, name, in_stock, qty, observed_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (store_id, it["sku_id"], it["name"], int(it["in_stock"]),
             it.get("qty"), it["observed_at"]))
    conn.commit()

def city_osa(conn, city, day=None):
    """Legacy example: retained for review; production OSA is implemented in app.py."""
    day = day or (datetime.now(timezone.utc).astimezone().date() - timedelta(days=1)).isoformat()
    rows = conn.execute("""SELECT i.in_stock FROM inventory i JOIN stores s ON s.store_id=i.store_id
        WHERE s.city=? AND substr(i.observed_at,1,10)=?""", (city, day)).fetchall()
    return round(100 * sum(int(r[0]) for r in rows) / len(rows), 2) if rows else None

if __name__ == "__main__":
    conn = sqlite3.connect("osa.db")
    conn.execute("CREATE TABLE IF NOT EXISTS stores (store_id TEXT, city TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS inventory (store_id TEXT, sku_id TEXT, name TEXT, in_stock INT, qty INT, observed_at TEXT)")
    print("Run sweep.py and app.py for the complete implementation.")
    conn.close()
