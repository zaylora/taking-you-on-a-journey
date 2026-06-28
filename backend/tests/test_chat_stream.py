"""流式链路单测（存活探针 + 校验层）。

M1 的全流式覆盖测试已由 Task 11 的 test_chat_stream_m2.py 接管。
此处仅保留不依赖图执行的两条测试：
- test_health：存活探针
- test_chat_rejects_empty_message：pydantic 校验层 422，图不执行
"""


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_rejects_empty_message(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422


from app.graph.stream import render_xhs_sources


def test_render_xhs_sources_basic():
    md = render_xhs_sources([
        {"title": "顺德一日游", "url": "https://www.xiaohongshu.com/explore/n1?xsec_token=t1&xsec_source=pc_search"},
        {"title": "", "url": "https://www.xiaohongshu.com/explore/n2"},
    ])
    assert md.startswith("\n\n## 笔记来源\n")
    assert "- [顺德一日游](https://www.xiaohongshu.com/explore/n1?xsec_token=t1&xsec_source=pc_search)" in md
    assert "- [小红书笔记](https://www.xiaohongshu.com/explore/n2)" in md


def test_render_xhs_sources_empty_returns_blank():
    assert render_xhs_sources([]) == ""


def test_render_xhs_sources_skips_missing_url():
    """验证无 url 的记录被跳过，且不被 limit 掩盖。"""
    md = render_xhs_sources(
        [
            {"title": "A", "url": "https://x/1"},
            {"title": "B", "url": ""},
            {"title": "C", "url": "https://x/3"},
        ],
        limit=6,
    )
    assert "[A](https://x/1)" in md
    assert "B" not in md       # 无 url 跳过
    assert "[C](https://x/3)" in md  # limit 足够大，C 应被渲染


def test_render_xhs_sources_limits():
    """验证 limit 截断：仅渲染前 N 条，超出部分不出现。"""
    md = render_xhs_sources(
        [
            {"title": "A", "url": "https://x/1"},
            {"title": "B", "url": "https://x/2"},
            {"title": "C", "url": "https://x/3"},
        ],
        limit=2,
    )
    assert "[A](https://x/1)" in md
    assert "[B](https://x/2)" in md
    assert "C" not in md       # 超出 limit
