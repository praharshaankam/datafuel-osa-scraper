# DataFuel QuickMart OSA Take-Home

Python 3.10+ implementation of a paginated QuickMart inventory scraper, SQLite persistence, and a FastAPI on-shelf availability (OSA) endpoint.

## 1. Setup (Windows PowerShell)

Open a terminal in this folder:

```powershell
py -3 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again.

## 2. Start the mock API

**Terminal 1** (leave it running):

```powershell
python mock_portal.py
```

**Terminal 2** (check API):

```powershell
curl.exe http://127.0.0.1:8765/v1/health
curl.exe -H "X-Api-Key: dfhire-2026" "http://127.0.0.1:8765/v1/stores?page=1"
```

Do not edit `mock_portal.py` or `API.md`.

## 3. Run the six required sweeps

Run each command in Terminal 2, one at a time. A careful sweep can take around a minute or longer. Keep Terminal 1 running.

```powershell
python sweep.py --as-of 2026-09-27T04:30:00Z
python sweep.py --as-of 2026-09-27T10:30:00Z
python sweep.py --as-of 2026-09-27T19:00:00Z
python sweep.py --as-of 2026-09-28T04:30:00Z
python sweep.py --as-of 2026-09-28T10:30:00Z
python sweep.py --as-of 2026-09-28T18:40:00Z
```

The database `osa.db` is created automatically. Run a sweep again to verify idempotency.

## 4. Start the OSA API

**Terminal 3** (from this folder, with venv active):

```powershell
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000/docs`, or query:

```powershell
curl.exe "http://127.0.0.1:8000/osa?city=Mumbai&date=2026-09-28"
curl.exe "http://127.0.0.1:8000/osa?city=Delhi&date=2026-09-28"
curl.exe "http://127.0.0.1:8000/osa?city=Bengaluru&date=2026-09-28"
```

The `date` is an IST calendar date. `osa_pct` is null with `status=no_data` when there are no observations. Incomplete store-sweeps are excluded and listed in `coverage`.

## 5. Run tests

```powershell
pytest -q
```

## Project files

- `sweep.py`: store discovery, inventory pagination, validation, retry/pacing, soft-ban detection, and persistence.
- `db.py`: schema and SQLite connection.
- `app.py`: read-only `/osa` endpoint.
- `tests/`: OSA, completeness, deduplication, and timezone tests.
- `review_me.py`, `REVIEW.md`: targeted fixes and review findings.
- `NOTES.md`, `AI_LOG.md`, `RECORDING.md`: decisions and submission documentation.

