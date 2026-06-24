from app.planning.context import collect_context


async def test_collect_context_replace_plan_fetches_all(fake_amap):
    fake_amap["get_weather"] = {"text": "晴", "temp": "20~28℃", "is_rainy": False, "source": "forecast"}
    fake_amap["search_poi"] = [{"name": "越秀公园", "poi_id": "G1", "lng": 113.27, "lat": 23.13}]
    ops = [{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 3}}]
    ctx = await collect_context(ops, {"normalized_req": {"city": "广州"}})
    assert ctx["weather"]["text"] == "晴"
    assert ctx["attractions"] and ctx["attractions"][0]["name"] == "越秀公园"
    assert ctx["restaurants"] is not None


async def test_collect_context_local_op_fetches_nothing(fake_amap):
    fake_amap["search_poi"] = [{"name": "不该被取", "poi_id": "X"}]
    ctx = await collect_context([{"op": "reorder", "day": 1}], {})
    assert ctx["attractions"] == [] and ctx["restaurants"] == [] and ctx["weather"] == {}


async def test_collect_context_uses_preferences_keywords(fake_amap):
    captured = {}

    async def _spy(city, keywords, poi_type="", page_size=20):
        captured.setdefault(poi_type, keywords)
        return []
    import app.tools.amap as amap
    amap.search_poi = _spy   # fake_amap 已 patch，这里再覆盖以捕获关键词
    ops = [{"op": "replace_plan", "requirements_patch": {"city": "广州", "days": 2}}]
    await collect_context(ops, {"normalized_req": {"preferences": {"travel": "博物馆", "food": "粤菜"}}})
    assert captured.get("风景名胜") == "博物馆"
    assert captured.get("餐饮") == "粤菜"
