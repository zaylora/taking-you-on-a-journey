import pytest


class _RecordingStructuredLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def with_structured_output(self, schema, **kwargs):
        self.calls.append((schema, kwargs))
        return self

    async def ainvoke(self, *_args, **_kwargs):
        return self.result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "node_name", "state", "result_factory"),
    [
        ("clarify", "_evaluate_gaps", {"query": "我想出去玩"}, "clarify"),
        ("dispatch", "dispatch", {"query": "成都3天", "clarify_history": []}, "dispatch"),
        ("itinerary", "itinerary", {"days": 1, "attractions": []}, "itinerary"),
    ],
)
async def test_structured_outputs_use_function_calling(monkeypatch, module_name, node_name, state, result_factory):
    if result_factory == "clarify":
        from app.graph.nodes import clarify as mod
        from app.graph.nodes.clarify import ClarifyGaps

        result = ClarifyGaps(gaps=[])
        args = (state,)
    elif result_factory == "dispatch":
        from app.graph.nodes import dispatch as mod
        from app.graph.nodes.dispatch import NormalizedReq

        result = NormalizedReq(city="成都", days=3)
        args = (state,)
    else:
        from app.graph.nodes import itinerary as mod
        from app.graph.nodes.itinerary import DayPlans

        result = DayPlans(days=[])
        args = (state, None)

    recorder = _RecordingStructuredLLM(result)
    monkeypatch.setattr(mod, "build_llm", lambda **_kwargs: recorder)

    await getattr(mod, node_name)(*args)

    assert recorder.calls
    assert recorder.calls[0][1]["method"] == "function_calling"
