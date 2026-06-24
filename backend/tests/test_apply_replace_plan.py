"""test_apply_replace_plan.py —— replace_plan 单元测试（TDD RED→GREEN）。

软填打桩：annotate_soft_fields 内有 except Exception 降级分支，
直接让 build_llm 抛异常，走降级返回 skeleton，无需构造合法 DayPlans。
"""
import pytest


@pytest.fixture(autouse=True)
def _stub_soft_fill(monkeypatch):
    """annotate_soft_fields 调 LLM 软填；桩成回显 skeleton（不改结构）。"""
    from app.itinerary import soft_fill

    class _Echo:
        def with_structured_output(self, *a, **k):
            return self

        async def ainvoke(self, *a, **k):
            # 软填 LLM 失败时 annotate_soft_fields 已有降级；这里直接抛让其走降级返回 skeleton
            raise RuntimeError("stub: skip soft fill")

    monkeypatch.setattr(soft_fill, "build_llm", lambda *a, **k: _Echo())


from app.planning.apply import replace_plan


async def test_replace_plan_empty_attractions_returns_empty(fake_amap):
    out = await replace_plan({"city": "广州", "days": 2}, {"attractions": [], "restaurants": []}, {})
    assert out["day_plans"] == [] and out["daily_centers"] == []
    assert out["relax_level"] == 0


async def test_replace_plan_builds_day_plans_from_pool(fake_amap, monkeypatch):
    # 提供 6 个分散景点 + 餐饮池，走真实 OR-Tools 纯函数链（距离用 haversine 降级）
    attrs = [{"name": f"景点{i}", "poi_id": f"A{i}", "lng": 113.2 + i * 0.02, "lat": 23.1 + i * 0.01,
              "rating": 4.5, "opentime": ""} for i in range(6)]
    rests = [{"name": f"餐厅{i}", "poi_id": f"R{i}", "lng": 113.2 + i * 0.02, "lat": 23.1, "type": "餐饮"}
             for i in range(4)]
    fake_amap["search_around"] = rests
    ctx = {"weather": {}, "attractions": attrs, "restaurants": rests}
    out = await replace_plan({"city": "广州", "days": 2, "preferences": {}}, ctx,
                             {"plan_version": 0}, None)
    assert len(out["day_plans"]) >= 1
    # 每天 items 含交通段交错（M6 不变量），首项非交通
    items = out["day_plans"][0]["items"]
    assert items and items[0].get("type") != "transport"
    assert all("center" in d for d in out["day_plans"])
