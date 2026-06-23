from app.graph.nodes.routing import route_after_plan, route_after_accommodation
from app.graph.nodes.budget import route_after_budget


def test_plan_new_always_full_chain():
    s = {"last_intent": "plan_new"}
    assert route_after_plan(s) == "accommodation"
    assert route_after_accommodation(s) == "budget"


def test_refine_change_hotel_goes_accommodation():
    s = {"last_intent": "refine_existing",
         "refine_request": {"needs_accommodation": True, "needs_budget_recheck": True}}
    assert route_after_plan(s) == "accommodation"
    assert route_after_accommodation(s) == "budget"


def test_refine_cost_change_skips_hotel_but_rechecks_budget():
    s = {"last_intent": "refine_existing",
         "refine_request": {"needs_budget_recheck": True}}
    assert route_after_plan(s) == "budget"


def test_refine_reorder_skips_both():
    s = {"last_intent": "refine_existing",
         "refine_request": {"needs_budget_recheck": False}}
    assert route_after_plan(s) == "summarize"


def test_budget_retry_only_for_plan_new():
    assert route_after_budget({"last_intent": "plan_new", "budget_check": {"retry": True}}) == "itinerary"
    # refine 超支不回全量 itinerary
    assert route_after_budget({"last_intent": "refine_existing", "budget_check": {"retry": True}}) == "summarize"
    assert route_after_budget({"last_intent": "plan_new", "budget_check": {"retry": False}}) == "summarize"
