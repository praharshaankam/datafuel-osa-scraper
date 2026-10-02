from sweep import normalise_item, parse_timestamp

def test_duplicate_sku_collapsing_is_dictionary_based():
    a = normalise_item({'sku_id':'SKU-1','name':'A','in_stock':True,'qty':0,'price':'12.5','observed_at':'2026-09-28T04:30:00Z'})
    b = normalise_item({'sku_id':'SKU-1','name':'A','in_stock':False,'qty':0,'price':12.5,'observed_at':'2026-09-28T10:00:00+05:30'})
    deduped = {x['sku_id']: x for x in [a,b]}
    assert len(deduped) == 1
    assert deduped['SKU-1']['in_stock'] == 0

def test_timestamp_offsets_normalise_to_same_utc():
    a = parse_timestamp('2026-09-28T04:30:00Z')
    b = parse_timestamp('2026-09-28T10:00:00+05:30')
    assert a == b

def test_naive_timestamp_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        parse_timestamp('2026-09-28T04:30:00')
