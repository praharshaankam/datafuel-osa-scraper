from datetime import date
from db import connect
from app import report_osa

def seed(path, rows):
    c = connect(path)
    with c:
        c.execute("INSERT INTO stores VALUES('MUM-001','Mumbai','Store 1',1,1,'now')")
        c.execute("INSERT INTO sweeps VALUES('2026-09-27T19:00:00Z','now')")
        for complete, reason, items in rows:
            c.execute("INSERT INTO store_sweeps VALUES('MUM-001','2026-09-27T19:00:00Z',?,?,?)", (complete, reason, len(items)))
            c.executemany("INSERT INTO inventory VALUES('MUM-001','2026-09-27T19:00:00Z',?,?,?,?,?,?)", items)
    c.close()

def test_city_osa_is_weighted_by_observation(tmp_path):
    path = tmp_path / 'weighted.db'
    c = connect(path)
    with c:
        c.execute("INSERT INTO stores VALUES('MUM-001','Mumbai','Store 1',1,1,'now')")
        c.execute("INSERT INTO sweeps VALUES('2026-09-27T19:00:00Z','now')")
        c.execute("INSERT INTO store_sweeps VALUES('MUM-001','2026-09-27T19:00:00Z',1,NULL,3)")
        for i, stock in enumerate([1,1,0]):
            c.execute("INSERT INTO inventory VALUES(?,?,?,?,?,?,?,?)", ('MUM-001','2026-09-27T19:00:00Z',f'SKU-{i}','Product',stock,0,10.0,'2026-09-27T19:00:00Z'))
    c.close()
    result = report_osa('Mumbai', date(2026,9,28), path)
    assert result['osa_pct'] == 66.67
    assert result['observations'] == 3

def test_incomplete_store_sweep_is_excluded(tmp_path):
    path = tmp_path / 'partial.db'
    c = connect(path)
    with c:
        c.execute("INSERT INTO stores VALUES('MUM-001','Mumbai','Store 1',1,1,'now')")
        c.execute("INSERT INTO sweeps VALUES('2026-09-27T19:00:00Z','now')")
        c.execute("INSERT INTO store_sweeps VALUES('MUM-001','2026-09-27T19:00:00Z',0,'portal returned partial snapshot',1)")
        c.execute("INSERT INTO inventory VALUES('MUM-001','2026-09-27T19:00:00Z','SKU-1','Product',0,0,10,'2026-09-27T19:00:00Z')")
    c.close()
    result = report_osa('Mumbai', date(2026,9,28), path)
    assert result['observations'] == 0
    assert result['osa_pct'] is None
    assert result['coverage']['incomplete'][0]['reason'] == 'portal returned partial snapshot'

def test_sweep_day_uses_ist_not_utc(tmp_path):
    path = tmp_path / 'ist.db'
    c = connect(path)
    with c:
        c.execute("INSERT INTO stores VALUES('MUM-001','Mumbai','Store 1',1,1,'now')")
        c.execute("INSERT INTO sweeps VALUES('2026-09-27T19:00:00Z','now')")
        c.execute("INSERT INTO store_sweeps VALUES('MUM-001','2026-09-27T19:00:00Z',1,NULL,1)")
        c.execute("INSERT INTO inventory VALUES('MUM-001','2026-09-27T19:00:00Z','SKU-1','Product',1,1,10,'2026-09-27T19:05:00Z')")
    c.close()
    assert report_osa('Mumbai', date(2026,9,28), path)['observations'] == 1
    assert report_osa('Mumbai', date(2026,9,27), path)['observations'] == 0

def test_invalid_city_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        report_osa('Chennai', date(2026,9,28), tmp_path / 'x.db')
