# Code Review: `review_me.py`

Problems below are ordered by their impact on data correctness and service reliability.

1. **Unbounded retry loop and no timeout (critical).** `fetch_inventory` catches every exception and retries forever. A wrong API key (401) never succeeds; a slow request can hang indefinitely. The revised helper sets a 5-second timeout, retries only transient failures with a fixed attempt limit, respects `Retry-After`, and surfaces a useful error.
2. **Mutable default list (critical).** `results=[]` is created once when Python defines the function. Calling `fetch_inventory` for MUM-001 and then MUM-002 can append MUM-001 products to the second call's result. Changed to `results=None` and create a fresh list per call.
3. **SQL string interpolation (critical).** A product name containing `'` can break the SQL statement, and untrusted text can alter the query. `save` now uses SQLite placeholders and bound parameters.
4. **Uses `qty` instead of the API's `in_stock`.** A valid in-stock item may report qty 0 (the mock deliberately includes this case); the original calculation marks it out of stock. Production `app.py` uses the boolean `in_stock` field.
5. **Unweighted mean of store percentages.** Averaging a small store and a large store equally differs from total in-stock observations divided by total observations. Production `app.py` computes the ratio over all valid observations.
6. **No completeness or soft-ban checks.** HTTP 200 from `edge`, `partial=true`, or a truncated page can be persisted as genuine inventory and bias OSA. `sweep.py` rejects non-origin, partial, and suspicious short non-final pages, and records incomplete status.
7. **Wrong date handling.** `date.today()` uses machine-local time and substring matching of `observed_at` does not convert UTC to IST. Production reporting assigns a sweep by its timezone-aware `as_of` timestamp converted to Asia/Kolkata.
8. **Not idempotent and no unique key.** Re-running inserts duplicate observations. Production storage uses a primary key on `(store_id, as_of_utc, sku_id)` and transactionally replaces a store snapshot.
9. **Recursive pagination can exhaust the call stack and has no cursor-loop guard.** Production scraper uses iterative pagination with a page limit and cursor tracking.
10. **Only two hard-coded stores and current timestamp.** The original does not page through the store roster or execute the six required historical sweeps. `sweep.py` retrieves all active stores and accepts the required timestamp through `--as-of`.

The three most consequential issues directly fixed in this file are bounded HTTP retries/timeouts, the mutable default, and SQL parameterization. The complete solution's scraper and reporting API additionally address the remaining correctness issues.
