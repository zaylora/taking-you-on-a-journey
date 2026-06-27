from app.agent.itinerary.budgeting import compute_budget, _sum_costs


def _day(day, items, hotel=None):
    d = {"day": day, "items": items}
    if hotel is not None:
        d["hotel"] = hotel
    return d


def _item(type_, name, cost):
    return {"type": type_, "name": name, "cost": cost}


def test_sum_costs_per_person_and_whole_room():
    dps = [_day(1, [_item("attraction", "A", 100), _item("meal", "M", 50)], hotel={"price": 400}),
           _day(2, [_item("attraction", "B", 80)])]
    s = _sum_costs(dps, num_people=2)
    # 过夜日=第1天；hotel 整间不乘人数；人均项乘 2
    assert s["breakdown"] == {"ticket": (100 + 80) * 2, "food": 50 * 2, "transport": 0, "hotel": 400}
    assert s["estimated"] == (100 + 80) * 2 + 50 * 2 + 400


def test_over_budget_retry_then_advice():
    dps = [_day(1, [_item("attraction", "A", 800), _item("meal", "M", 300)], hotel={"price": 1000}),
           _day(2, [])]
    res = compute_budget(dps, num_people=1, limit=1000, retry_count=0)
    assert res["budget_check"]["over"] is True
    assert res["budget_check"]["retry"] is True
    assert res["retry_count"] == 1
    assert res["advice"]["over_amount"] > 0


def test_retry_capped_at_max():
    dps = [_day(1, [_item("attraction", "A", 5000)], hotel={"price": 1}), _day(2, [])]
    res = compute_budget(dps, num_people=1, limit=100, retry_count=2)
    assert res["budget_check"]["over"] is True
    assert res["budget_check"]["retry"] is False  # retry_count 已达 _MAX_RETRY
    assert "已尽力压缩" in res["budget_check"]["note"]
