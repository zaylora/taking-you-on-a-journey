# -*- coding: utf-8 -*-
"""单元：工具调用进度文案按本次参数动态生成，避免暴露内部函数名。"""

from app.services.tool_labels import build_tool_label


def test_research_xhs_travel_guide_label_uses_city_days_and_keywords():
    label = build_tool_label(
        "research_xhs_travel_guide",
        {
            "city": "顺德",
            "days": 2,
            "travel_style": "亲子",
            "keywords": ["早茶", "清晖园"],
        },
    )

    assert label == "研究顺德2天亲子小红书攻略：早茶、清晖园"


def test_search_labels_include_city_and_keyword_context():
    assert build_tool_label(
        "search_attractions",
        {"city": "佛山", "keywords": "顺德 热门景点"},
    ) == "搜索佛山景点：顺德 热门景点"

    assert build_tool_label(
        "search_restaurants",
        {"city": "佛山", "keywords": "华盖路早茶"},
    ) == "搜索佛山餐厅：华盖路早茶"


def test_weather_and_budget_labels_include_useful_arguments():
    assert build_tool_label("get_weather", {"city": "佛山"}) == "查询佛山天气"
    assert build_tool_label(
        "compute_budget_tool",
        {"num_people": 3, "limit": 2500},
    ) == "核算3人预算：2500元"


def test_unknown_tool_label_never_exposes_snake_case_name():
    assert build_tool_label("new_internal_tool_name", {"city": "广州"}) == "执行工具：广州"
    assert build_tool_label("new_internal_tool_name", {}) == "执行工具"
