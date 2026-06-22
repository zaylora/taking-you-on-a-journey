from app.itinerary.matrix import MatrixCache


def test_put_get_roundtrip(tmp_path):
    db = str(tmp_path / "c.sqlite")
    cache = MatrixCache(db)
    assert cache.get("A", "B") is None
    cache.put("A", "B", 12.5)
    assert cache.get("A", "B") == 12.5


def test_missing_key_returns_none(tmp_path):
    cache = MatrixCache(str(tmp_path / "c.sqlite"))
    assert cache.get("X", "Y") is None
