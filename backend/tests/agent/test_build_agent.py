from langgraph.checkpoint.memory import MemorySaver


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
