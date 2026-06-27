from app.agent.domain.diffing import diff_changed_days


def _day(day, items, hotel=None):
    d = {"day": day, "items": items}
    if hotel is not None:
        d["hotel"] = hotel
    return d


def _it(type_, name, poi_id=""):
    return {"type": type_, "name": name, "poi_id": poi_id}


def test_no_change_returns_empty():
    a = [_day(1, [_it("attraction", "故宫", "p1")])]
    assert diff_changed_days(a, a) == []


def test_full_replan_all_days_changed():
    old = []
    new = [_day(1, [_it("attraction", "A")]), _day(2, [_it("attraction", "B")])]
    assert diff_changed_days(old, new) == [1, 2]


def test_single_day_item_change():
    old = [_day(1, [_it("attraction", "A", "p1")]), _day(2, [_it("attraction", "B", "p2")])]
    new = [_day(1, [_it("attraction", "A", "p1")]), _day(2, [_it("attraction", "C", "p3")])]
    assert diff_changed_days(old, new) == [2]


def test_hotel_change_marks_day():
    old = [_day(1, [_it("attraction", "A")], hotel={"name": "H1", "poi_id": "h1"})]
    new = [_day(1, [_it("attraction", "A")], hotel={"name": "H2", "poi_id": "h2"})]
    assert diff_changed_days(old, new) == [1]


def test_removed_day_marked():
    old = [_day(1, [_it("attraction", "A")]), _day(2, [_it("attraction", "B")])]
    new = [_day(1, [_it("attraction", "A")])]
    assert diff_changed_days(old, new) == [2]
