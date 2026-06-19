"""M5 SQLite checkpointer persists graph state across graph instances."""
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.graph.builder import build_graph


async def test_sqlite_checkpointer_restores_thread_state(tmp_path, monkeypatch):
    from app.graph.nodes import clarify as c, dispatch as d, itinerary as it, summarize as s
    from app.graph.nodes.dispatch import NormalizedReq
    from app.graph.nodes.itinerary import DayPlans, DayPlan, PlanItem, Location, DayWeather
    from tests.conftest import make_fake_build_llm

    async def no_gaps(_state, _config=None):
        return []

    monkeypatch.setattr(c, "_evaluate_gaps", no_gaps)
    monkeypatch.setattr(d, "build_llm", make_fake_build_llm(
        structured=NormalizedReq(city="成都", days=1, num_people=1)))
    monkeypatch.setattr(it, "build_llm", make_fake_build_llm(structured=DayPlans(days=[
        DayPlan(day=1, weather=DayWeather(), center=Location(lng=104.0, lat=30.6),
                items=[PlanItem(type="attraction", name="武侯祠", poi_id="B1",
                                location=Location(lng=104.0, lat=30.6))])
    ])))
    monkeypatch.setattr(s, "build_llm", make_fake_build_llm(tokens=["行程", "完成"]))

    db_path = str(tmp_path / "checkpoints.sqlite")
    config = {"configurable": {"thread_id": "persist-thread"}}

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        await saver.setup()
        graph = build_graph(checkpointer=saver)
        await graph.ainvoke({"query": "成都1天", "messages": [], "clarified": False, "clarify_round": 0}, config=config)

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        await saver.setup()
        graph = build_graph(checkpointer=saver)
        snap = await graph.aget_state(config)

    assert snap.values["city"] == "成都"
    assert snap.values["day_plans"][0]["items"][0]["name"] == "武侯祠"
