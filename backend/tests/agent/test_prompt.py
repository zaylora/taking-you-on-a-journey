from app.agent.prompt import TRIP_AGENT_SYS


def test_prompt_covers_key_directives():
    p = TRIP_AGENT_SYS
    # 必须提及关键工具与约束，确保 agent 知道能力边界
    for kw in ("ask_user", "finalize_plan", "compute_budget", "预算", "澄清"):
        assert kw in p, f"系统提示缺少关键指引：{kw}"
    assert len(p) > 200
