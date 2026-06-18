from app.graph.nodes.budget import (
    compute_budget, budget, route_after_budget, _sum_costs,
)


def _day(day, items, hotel=None):
    d = {"day": day, "items": items}
    if hotel is not None:
        d["hotel"] = hotel
    return d


def _item(type_, name, cost):
    return {"type": type_, "name": name, "cost": cost}


def test_sum_costs_classifies_and_multiplies_by_people():
    dps = [_day(1, [_item("attraction", "A", 100), _item("meal", "M", 50),
                    _item("transport", "", 10)], hotel={"price": 400})]
    s = _sum_costs(dps, num_people=2)
    assert s["breakdown"] == {"ticket": 200, "food": 100, "transport": 20, "hotel": 400}
    assert s["estimated"] == 720  # (100+50+10)*2 + 400


def test_under_budget_no_over_no_retry():
    dps = [_day(1, [_item("attraction", "A", 100)], hotel={"price": 200})]
    res = compute_budget(dps, num_people=1, limit=1000, retry_count=0)
    assert res["budget_check"]["over"] is False
    assert res["budget_check"]["retry"] is False
    assert res["advice"] is None
    assert res["retry_count"] == 0


def test_over_budget_triggers_retry_with_advice():
    dps = [_day(1, [_item("attraction", "A", 800), _item("meal", "M", 300)],
                hotel={"price": 1000})]
    res = compute_budget(dps, num_people=1, limit=1000, retry_count=0)
    bc = res["budget_check"]
    assert bc["over"] is True and bc["retry"] is True
    assert bc["retry_count"] == 1
    assert res["advice"]["over_amount"] == bc["estimated"] - 1000
    assert res["advice"]["cut_suggestions"][0]["name"] == "A"  # 最贵项排前


def test_limit_zero_means_unlimited():
    dps = [_day(1, [_item("attraction", "A", 99999)], hotel={"price": 99999})]
    res = compute_budget(dps, num_people=2, limit=0, retry_count=0)
    assert res["budget_check"]["over"] is False
    assert res["budget_check"]["retry"] is False


def test_retry_cap_at_two_sets_note():
    dps = [_day(1, [_item("attraction", "A", 5000)])]
    res = compute_budget(dps, num_people=1, limit=1000, retry_count=2)
    bc = res["budget_check"]
    assert bc["over"] is True
    assert bc["retry"] is False            # 到顶不再回退
    assert bc["retry_count"] == 2
    assert bc["note"].startswith("已尽力压缩")


def test_node_emits_advice_only_when_retry():
    over_state = {"day_plans": [_day(1, [_item("attraction", "A", 5000)])],
                  "num_people": 1, "budget": 1000, "retry_count": 0}
    out = budget(over_state)
    assert out["retry_count"] == 1 and "budget_advice" in out
    under_state = {"day_plans": [_day(1, [_item("attraction", "A", 10)])],
                   "num_people": 1, "budget": 1000, "retry_count": 0}
    assert "budget_advice" not in budget(under_state)


def test_route_reads_retry_flag():
    assert route_after_budget({"budget_check": {"retry": True}}) == "itinerary"
    assert route_after_budget({"budget_check": {"retry": False}}) == "summarize"
    assert route_after_budget({}) == "summarize"
