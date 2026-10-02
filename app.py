"""Read-only OSA reporting API. Start with: uvicorn app:app --reload"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query

from db import connect

app = FastAPI(title="QuickMart OSA API", version="1.0.0")
IST = ZoneInfo("Asia/Kolkata")
CITIES = {"Mumbai", "Delhi", "Bengaluru"}

def report_osa(city: str, day: date, db_path=None):
    if city not in CITIES:
        raise ValueError("city must be Mumbai, Delhi or Bengaluru")
    conn = connect(db_path) if db_path else connect()
    try:
        stores = conn.execute("SELECT store_id FROM stores WHERE city=? AND is_active=1 ORDER BY store_id", (city,)).fetchall()
        expected_ids = {r["store_id"] for r in stores}
        start_utc = datetime.combine(day, datetime.min.time(), IST).astimezone(timezone.utc)
        end_utc = datetime.combine(day + timedelta(days=1), datetime.min.time(), IST).astimezone(timezone.utc)
        sweep_rows = conn.execute("SELECT as_of_utc FROM sweeps ORDER BY as_of_utc").fetchall()
        relevant = []
        for row in sweep_rows:
            ts = datetime.fromisoformat(row["as_of_utc"].replace("Z", "+00:00"))
            if start_utc <= ts < end_utc:
                relevant.append(row["as_of_utc"])
        incomplete, completed_ids = [], set()
        sku_stats = {}
        total_obs = total_stock = 0
        for sweep in relevant:
            statuses = conn.execute("""SELECT ss.store_id,ss.complete,ss.reason FROM store_sweeps ss
                 JOIN stores s ON s.store_id=ss.store_id WHERE s.city=? AND s.is_active=1 AND ss.as_of_utc=?""",
                 (city, sweep)).fetchall()
            status_map = {r["store_id"]: r for r in statuses}
            for sid in sorted(expected_ids):
                status = status_map.get(sid)
                if status is None:
                    incomplete.append({"store_id": sid, "sweep": sweep, "reason": "no sweep status recorded"})
                elif status["complete"] != 1:
                    incomplete.append({"store_id": sid, "sweep": sweep, "reason": status["reason"] or "incomplete"})
                else:
                    completed_ids.add(sid)
                    rows = conn.execute("""SELECT sku_id,name,in_stock FROM inventory
                        WHERE store_id=? AND as_of_utc=?""", (sid, sweep)).fetchall()
                    for row in rows:
                        stat = sku_stats.setdefault(row["sku_id"], {"name": row["name"], "observations": 0, "in_stock": 0})
                        # Keep the most recently observed display name for renamed products.
                        stat["name"] = row["name"]
                        stat["observations"] += 1
                        stat["in_stock"] += row["in_stock"]
                        total_obs += 1
                        total_stock += row["in_stock"]
        # A store is counted complete only if it has a complete status for every selected sweep.
        incomplete_store_ids = {x["store_id"] for x in incomplete}
        stores_complete = len(expected_ids - incomplete_store_ids) if relevant else 0
        skus = []
        for sku_id, stat in sorted(sku_stats.items()):
            count = stat["observations"]
            skus.append({"sku_id": sku_id, "name": stat["name"], "observations": count,
                         "in_stock": stat["in_stock"],
                         "osa_pct": round(100 * stat["in_stock"] / count, 2) if count else None})
        return {"city": city, "date": day.isoformat(),
                "status": "ok" if total_obs else "no_data",
                "osa_pct": round(100 * total_stock / total_obs, 2) if total_obs else None,
                "observations": total_obs,
                "coverage": {"stores_expected": len(expected_ids), "stores_complete": stores_complete,
                             "sweeps_expected": len(relevant), "sweeps_found": len(relevant), "incomplete": incomplete},
                "skus": skus}
    finally:
        conn.close()

@app.get("/osa")
def osa(city: str = Query(...), date_value: str | None = Query(default=None, alias="date")):
    if city not in CITIES:
        raise HTTPException(status_code=400, detail="city must be Mumbai, Delhi or Bengaluru")
    if date_value is None:
        day = datetime.now(IST).date() - timedelta(days=1)
    else:
        try:
            day = date.fromisoformat(date_value)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must use YYYY-MM-DD format")
        if day.isoformat() != date_value:
            raise HTTPException(status_code=400, detail="date must use YYYY-MM-DD format")
    return report_osa(city, day)
