from app.agent.state import TripState


def test_tripstate_has_business_fields():
    ann = TripState.__annotations__
    for field in ("day_plans", "changed_days", "plan_version", "budget_check", "retry_count", "summary", "xhs_sources"):
        assert field in ann, f"缺业务字段 {field}"


def test_tripstate_inherits_messages():
    # AgentState 提供 messages；继承后应可见（在 MRO 注解里）
    all_ann = {}
    for klass in TripState.__mro__:
        all_ann.update(getattr(klass, "__annotations__", {}))
    assert "messages" in all_ann
