"""Fetch one complete QuickMart inventory sweep and persist it safely."""
import argparse
import logging
import os
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests

from db import connect

BASE_URL = os.getenv("QUICKMART_URL", "http://127.0.0.1:8765").rstrip("/")
API_KEY = os.getenv("QUICKMART_API_KEY", "dfhire-2026")
HEADERS = {"X-Api-Key": API_KEY}
REQUEST_TIMEOUT = 5
MAX_ATTEMPTS = 5
REQUEST_GAP = 0.55  # ~1.8 requests/sec, comfortably below burst/fair-use limits
MAX_PAGES = 100
SOFT_BAN_PAUSE = 30
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("quickmart-sweep")

class FetchError(Exception):
    pass

class SoftBanError(FetchError):
    pass

def parse_timestamp(value: str) -> datetime:
    """Parse ISO-8601 timestamp with timezone and return UTC-aware datetime."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return dt.astimezone(timezone.utc)

def utc_text(value: str) -> str:
    return parse_timestamp(value).isoformat(timespec="seconds").replace("+00:00", "Z")

def pace():
    time.sleep(REQUEST_GAP)

def retry_after_seconds(response):
    raw = response.headers.get("Retry-After", "2")
    try:
        return max(0.0, min(float(raw), 60.0))
    except ValueError:
        try:
            dt = parsedate_to_datetime(raw)
            return max(0.0, min((dt - datetime.now(dt.tzinfo)).total_seconds(), 60.0))
        except Exception:
            return 2.0

def get_json(path, params=None):
    """Bounded retries: retry 429/5xx/timeouts, fail fast on permanent 4xx."""
    url = urljoin(BASE_URL + "/", path.lstrip("/"))
    last_reason = "unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        pace()
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_reason = f"network/timeout: {exc.__class__.__name__}"
            retryable = True
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise FetchError(f"invalid JSON: {exc}") from exc
            if response.status_code == 429:
                last_reason = "http 429 rate limited"
                wait = retry_after_seconds(response)
                retryable = True
            elif response.status_code in (500, 502, 503, 504):
                last_reason = f"http {response.status_code}"
                retryable = True
            else:
                raise FetchError(f"permanent http {response.status_code}: {response.text[:160]}")
        if attempt == MAX_ATTEMPTS or not retryable:
            break
        wait = locals().get("wait", min(0.75 * (2 ** (attempt - 1)), 8) + random.uniform(0, .25))
        LOG.warning("%s; retry %s/%s in %.1fs", last_reason, attempt, MAX_ATTEMPTS, wait)
        time.sleep(wait)
    raise FetchError(f"gave up after {MAX_ATTEMPTS} attempts ({last_reason})")

def fetch_stores():
    stores, page, seen_pages = [], 1, set()
    while page is not None:
        if page in seen_pages:
            raise FetchError(f"store pagination loop at page {page}")
        seen_pages.add(page)
        body = get_json("/v1/stores", {"page": page})
        chunk = body.get("stores")
        if not isinstance(chunk, list):
            raise FetchError("store response missing stores list")
        stores.extend(chunk)
        page = body.get("next_page")
    # Track active network members, even if temporarily not serviceable.
    return [s for s in stores if s.get("is_active") is True]

def normalise_item(item):
    sku = item.get("sku_id")
    name = item.get("name")
    stock = item.get("in_stock")
    if not sku or not isinstance(name, str) or not isinstance(stock, bool):
        raise FetchError("item missing sku_id/name/boolean in_stock")
    try:
        qty = int(item["qty"]) if item.get("qty") is not None else None
        price = float(item["price"]) if item.get("price") is not None else None
        observed = utc_text(item["observed_at"])
    except (ValueError, TypeError, KeyError) as exc:
        raise FetchError(f"invalid item fields for {sku}: {exc}") from exc
    return {"sku_id": str(sku), "name": name, "in_stock": int(stock), "qty": qty,
            "price": price, "observed_at_utc": observed}

def fetch_one_store(store_id, as_of):
    """Return (unique items, None) or (None, reason); never return partial data."""
    for recovery_round in range(3):
        cursor, seen_cursors, items = "0", set(), {}
        try:
            for page_number in range(1, MAX_PAGES + 1):
                if cursor in seen_cursors:
                    raise FetchError(f"pagination cursor loop at {cursor}")
                seen_cursors.add(cursor)
                body = get_json(f"/v1/stores/{store_id}/inventory", {"as_of": as_of, "cursor": cursor})
                meta = body.get("meta") or {}
                if meta.get("source") != "origin":
                    raise SoftBanError(f"soft_ban: source={meta.get('source', 'missing')}")
                if body.get("partial") is True:
                    raise FetchError("portal returned partial snapshot")
                page_items = body.get("items")
                if not isinstance(page_items, list):
                    raise FetchError("response missing items list")
                next_cursor = body.get("next_cursor")
                # In this API a non-final page normally contains 15 records. A shorter
                # page with a continuation can indicate truncated/degraded data.
                if next_cursor is not None and len(page_items) < 15:
                    raise FetchError("short non-final page; possible truncated response")
                for raw in page_items:
                    item = normalise_item(raw)
                    items[item["sku_id"]] = item  # collapse intentional duplicate page rows
                if next_cursor is None:
                    return list(items.values()), None
                cursor = str(next_cursor)
            raise FetchError(f"exceeded page safety limit ({MAX_PAGES})")
        except SoftBanError as exc:
            LOG.warning("%s at %s; pausing before full-store restart", exc, store_id)
            if recovery_round < 2:
                time.sleep(SOFT_BAN_PAUSE * (recovery_round + 1))
                continue
            return None, "soft_ban after recovery attempts"
        except (FetchError, requests.RequestException, ValueError) as exc:
            return None, str(exc)
    return None, "soft_ban after recovery attempts"

def save_store(conn, store, as_of, items, reason=None):
    """Atomic and idempotent store-sweep replacement; don't downgrade complete data."""
    sid = store["store_id"]
    conn.execute("INSERT OR IGNORE INTO sweeps(as_of_utc, created_at_utc) VALUES (?, ?)",
                 (as_of, datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")))
    existing = conn.execute("SELECT complete FROM store_sweeps WHERE store_id=? AND as_of_utc=?",
                            (sid, as_of)).fetchone()
    if existing and existing["complete"] == 1 and reason is not None:
        conn.commit()
        return "preserved"
    with conn:
        conn.execute("""INSERT INTO stores(store_id,city,name,is_active,is_serviceable,updated_at)
                     VALUES(?,?,?,?,?,?) ON CONFLICT(store_id) DO UPDATE SET
                     city=excluded.city,name=excluded.name,is_active=excluded.is_active,
                     is_serviceable=excluded.is_serviceable,updated_at=excluded.updated_at""",
                     (sid, store["city"], store.get("name", sid), int(store["is_active"]),
                      int(bool(store.get("is_serviceable"))), datetime.now(timezone.utc).isoformat()))
        conn.execute("DELETE FROM inventory WHERE store_id=? AND as_of_utc=?", (sid, as_of))
        conn.execute("DELETE FROM store_sweeps WHERE store_id=? AND as_of_utc=?", (sid, as_of))
        conn.execute("INSERT INTO store_sweeps(store_id,as_of_utc,complete,reason,item_count) VALUES(?,?,?,?,?)",
                     (sid, as_of, int(reason is None), reason, len(items or [])))
        if reason is None:
            conn.executemany("""INSERT INTO inventory
                (store_id,as_of_utc,sku_id,name,in_stock,qty,price,observed_at_utc)
                VALUES(?,?,?,?,?,?,?,?)""",
                [(sid, as_of, x["sku_id"], x["name"], x["in_stock"], x["qty"], x["price"], x["observed_at_utc"])
                 for x in items])
    return "complete" if reason is None else "incomplete"

def run_sweep(as_of, db_path=None):
    as_of = utc_text(as_of)
    started = time.monotonic()
    conn = connect(db_path) if db_path else connect()
    try:
        stores = fetch_stores()
        complete, incomplete = 0, []
        for store in stores:
            sid = store["store_id"]
            items, reason = fetch_one_store(sid, as_of)
            result = save_store(conn, store, as_of, items or [], reason)
            if result == "complete" or result == "preserved":
                complete += 1
            else:
                incomplete.append((sid, reason or "unknown"))
            LOG.info("%s: %s (%s items)", sid, result, len(items or []))
        elapsed = time.monotonic() - started
        print(f"{len(stores)} stores: {complete} complete, {len(incomplete)} incomplete" +
              (" (" + "; ".join(f"{sid}: {why}" for sid, why in incomplete) + ")" if incomplete else "") +
              f" · {elapsed:.1f}s")
        return {"expected": len(stores), "complete": complete, "incomplete": incomplete}
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser(description="Collect one QuickMart inventory sweep")
    parser.add_argument("--as-of", required=True, help="Timezone-aware ISO-8601 timestamp")
    args = parser.parse_args()
    try:
        run_sweep(args.as_of)
    except (ValueError, FetchError, requests.RequestException) as exc:
        parser.error(str(exc))

if __name__ == "__main__":
    main()
