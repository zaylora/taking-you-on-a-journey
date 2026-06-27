from app.agent.itinerary.schemas import DayPlans, PlanItem, ITINERARY_SYS


def test_dayplans_schema_parses():
    dp = DayPlans(days=[{"day": 1, "items": [{"type": "attraction", "name": "故宫"}]}])
    assert dp.days[0].day == 1
    assert dp.days[0].items[0].name == "故宫"


def test_planitem_alias_from():
    it = PlanItem(type="transport", **{"from": "A"}, to="B")
    assert it.from_ == "A"


def test_itinerary_sys_nonempty():
    assert len(ITINERARY_SYS) > 50
