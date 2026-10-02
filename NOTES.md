# Implementation Notes

## Architecture and decisions
- `sweep.py` calls QuickMart, validates and normalizes each response, then writes complete store snapshots to SQLite through `db.py`. `app.py` is read-only and calculates OSA from the database.
- Track stores with `is_active=true`, even when `is_serviceable=false`: serviceability is a live ordering flag and can change during the day, while active indicates network membership. Inactive stores are excluded from expected coverage.
- A store-sweep is committed atomically. A complete rerun replaces its earlier snapshot; an incomplete rerun does not downgrade previously complete data. An incomplete new attempt stores its reason and contributes no inventory rows.
- Requests are sequential and paced (~1.8 requests/second), with 5-second timeout, bounded retries, exponential backoff for transient failures, and `Retry-After` handling for 429. Permanent 4xx errors fail promptly.
- Only `meta.source=origin` is accepted. `edge`, `partial=true`, invalid structures, cursor loops, and suspicious short non-final pages make the store-sweep incomplete. On edge data, pause and restart that store from cursor 0. A legitimate empty inventory is accepted only when the response is complete and from origin.
- Timestamps are timezone-validated and normalized to UTC for storage. OSA day grouping uses the sweep's `as_of` moment converted to IST, not the item's `observed_at`, so every store in one sweep belongs to the same reporting day. Prices are converted to numeric values; SKU IDs are stable identifiers; stock is determined only by `in_stock`.
- Duplicate SKU rows across pages are collapsed by `sku_id`. Database primary keys make reruns idempotent.
- `stores_expected` is the number of active stores in the city; `stores_complete` is the number without any missing/incomplete store-sweep for the requested day. The `incomplete` list identifies each store and sweep pair. If there are no valid observations, `osa_pct` is null and status is `no_data`.

## Business questions

**Delhi availability changed from 92% to 41%:** First verify coverage and completeness for both periods, including missing store-sweeps, partial responses, `edge` responses, retries, and changes in active-store population. Confirm the same IST date boundaries and OSA denominator, then inspect SKU/store-level contributions and whether product mix changed. Only after reconciling the data would I explain the movement, with coverage and caveats.

**Dashboard sales ₹4.20 lakh versus store sum ₹4.61 lakh:** I would not arbitrarily choose either. Reconcile source-of-truth definitions, time zone/date boundaries, duplicate or delayed transactions, returns/refunds, adjustments, and store inclusion. Show the authoritative, reconciled figure only after documenting the discrepancy; otherwise label both values with their source and the unresolved ₹41,000 difference.

**Where not to use an LLM:** Do not use an LLM to decide stock status, parse/normalize timestamps, enforce uniqueness/transactions, classify completeness, or calculate OSA. These are deterministic decisions that need repeatable, auditable results. An LLM may help draft explanations, but the numeric facts should come from code and validated data.

## Scaling to 20,000 stores every 30 minutes (bonus)
Use a durable job queue, partition work by city/store, bounded concurrency per partner, and partner-specific rate limits. Persist checkpoints and retry schedules, use bulk database writes and an indexed production database, add metrics/alerts for coverage and edge responses, and make jobs idempotent. Confirm partner quotas and data retention requirements before increasing traffic.
