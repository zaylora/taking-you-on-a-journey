from langgraph.checkpoint.memory import MemorySaver
from langchain.agents.middleware import ContextEditingMiddleware, SummarizationMiddleware


def test_build_graph_returns_compiled_agent(monkeypatch):
    # 不触发真实 LLM：patch build_llm 返回一个可 bind_tools 的占位
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatResult, ChatGeneration
    from langchain_core.messages import AIMessage

    class _Stub(BaseChatModel):
        @property
        def _llm_type(self): return "stub"
        def bind_tools(self, tools, **kw): return self
        def _generate(self, messages, stop=None, run_manager=None, **kw):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    monkeypatch.setattr("app.agent.build.build_llm", lambda *a, **k: _Stub())
    from app.graph.builder import build_graph
    graph = build_graph(checkpointer=MemorySaver())
    assert hasattr(graph, "astream_events")
    assert hasattr(graph, "aget_state")


def test_context_middleware_thresholds(monkeypatch):
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.messages import AIMessage

    class _Stub(BaseChatModel):
        @property
        def _llm_type(self): return "stub"
        def bind_tools(self, tools, **kw): return self
        def _generate(self, messages, stop=None, run_manager=None, **kw):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    monkeypatch.setattr("app.agent.build.build_llm", lambda *a, **k: _Stub())

    from app.agent.build import _build_context_middleware

    middleware = _build_context_middleware()
    context_editor = next(m for m in middleware if isinstance(m, ContextEditingMiddleware))
    summarizer = next(m for m in middleware if isinstance(m, SummarizationMiddleware))

    edit = context_editor.edits[0]
    assert edit.trigger == 16_000
    assert edit.clear_at_least == 5_000
    assert edit.keep == 4
    assert edit.exclude_tools == ("finalize_plan", "compute_budget_tool")

    assert summarizer.trigger == [{"tokens": 40_000}, {"messages": 28}]
    assert summarizer.keep == ("tokens", 10_000)
    assert summarizer.trim_tokens_to_summarize == 16_000
