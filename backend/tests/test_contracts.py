from app.core import constants as C
from app.core.config import Settings
from app.schemas.chat import ChatRequest
from app.graph.state import TripState


def test_event_constants_present():
    assert C.EVENT_SESSION == "session"
    assert C.EVENT_CLARIFY == "clarify"
    assert C.MAX_CLARIFY_ROUNDS == 4


def test_node_labels_cover_all_nodes():
    assert C.NODES == {"clarify", "dispatch", "weather", "attractions",
                       "restaurants", "transport", "itinerary", "summarize"}
    for n in C.NODES:
        assert C.NODE_LABELS.get(n)  # 每个节点都有非空中文文案


def test_chat_request_thread_id_optional():
    assert ChatRequest(message="hi").thread_id is None
    assert ChatRequest(message="hi", thread_id="abc").thread_id == "abc"


def test_settings_has_amap_key():
    s = Settings(_env_file=None)
    assert s.amap_web_key.get_secret_value() == ""  # 默认空


def test_tripstate_has_m2_keys():
    keys = TripState.__annotations__
    for k in ("city", "days", "preferences", "clarify_history", "clarified",
              "clarify_round", "weather", "attractions", "restaurants",
              "transport", "daily_centers", "day_plans", "normalized_req"):
        assert k in keys
