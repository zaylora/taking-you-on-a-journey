# 小红书图文解析与攻略型检索实施计划

> **给自动执行的开发代理：** 必需子技能：执行本计划时使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`。所有步骤使用复选框（`- [ ]`）跟踪。

**目标：** 升级小红书旅行研究能力，让检索关键词稳定偏向“某某旅游攻略”这类攻略型描述，并在读取图文笔记时用多模态 LLM 解析图片信息，再汇入旅行研究摘要。

**架构：** 继续以 `xiaohongshu-cli` 作为只读数据源，不新增小红书直连实现。主要在 `backend/app/agent/tools/xhs.py` 内增加四类小辅助函数：攻略型关键词生成、笔记图片 URL 抽取、多模态图文解析、失败降级；随后把图文解析结果喂给现有 `research_xhs_travel_guide` 的结构化研究摘要流程。低层工具保持原有 `ok/data/error` 响应外壳，只做加字段，不破坏调用方。

**技术栈：** Python 3.11+、FastAPI、LangChain 1.3.9、LangGraph 1.2.5、Pydantic 2、`xiaohongshu-cli>=0.6.4`、pytest。

## 全局约束

- 不新增图片解析依赖；复用现有 `build_llm` 工厂和 LangChain `HumanMessage` 多模态消息块。
- 小红书工具继续保持只读：不接入发布、点赞、收藏、评论、关注、删除等账号写操作。
- 图片解析失败不能阻断小红书文本研究；失败时返回警告，并继续生成纯文本研究摘要。
- 默认每篇笔记最多解析 4 张图片，硬上限 6 张。
- 旅行研究搜索词必须包含 `攻略`；某个城市的第一个查询必须是 `{city}旅游攻略`。
- 测试不得调用真实小红书、OpenAI、Anthropic 或高德服务。
- 保留 CLI 的 `ok/data/error` 响应外壳；只能追加字段，不删除或重命名既有响应 key。

---

## 项目现状

- 小红书工具集中在 `backend/app/agent/tools/xhs.py`。
- Agent 工具注册在 `backend/app/agent/build.py` 和 `backend/app/agent/tools/__init__.py`。
- `research_xhs_travel_guide` 已经会搜索、提取笔记目标、读取笔记、可选读取评论，并把压缩后的 JSON 发给 `XHS_RESEARCH_SYS` 生成结构化研究摘要。
- 当前关键词生成以 `{city}旅游攻略` 开头，但后续会退化成 `{city}美食`、`{city}避雷`、`{city}{travel_style}` 这类泛词，精准度不如攻略型搜索。
- 当前图文处理是纯文本：只压缩笔记 JSON 给文本 LLM，没有抽取 `note_card.image_list`，也没有把图片 URL 交给视觉模型。
- 本地安装的 `xiaohongshu-cli` 规范化器会读取 `note_card.image_list` 并计算 `image_count`，说明上游载荷通常带图片字段。

## 文件结构

- 修改 `backend/app/agent/tools/xhs.py`：关键词辅助函数、图片 URL 抽取、视觉 Pydantic 数据结构、多模态辅助函数、`xhs_read_note` 附加图文解析、`research_xhs_travel_guide` 集成。
- 修改 `backend/app/agent/prompt.py`：补充攻略型检索和图文解析规则。
- 修改 `backend/tests/agent/test_tools.py`：覆盖关键词、图片抽取、多模态消息、工具集成。
- 修改 `backend/tests/agent/test_prompt.py`：锁定提示词规则，防止以后回退成泛搜索。
- 修改 `plan/20260628_xhs_multimodal_guide_search/README.md`：实现后记录实际改动和测试结果。

### 任务 1：攻略型小红书关键词生成

**文件：**
- 修改：`backend/app/agent/tools/xhs.py`
- 修改：`backend/tests/agent/test_tools.py`
- 修改：`backend/app/agent/prompt.py`
- 修改：`backend/tests/agent/test_prompt.py`

**接口：**
- 产出：`_build_xhs_guide_keywords(city: str, days: int, travel_style: str, keywords: list[str] | None, limit: int = 6) -> list[str]`
- 产出：`_normalize_xhs_search_keyword(keyword: str) -> str`
- 消费：现有 `research_xhs_travel_guide(...)` 和 `xhs_search_notes(...)`

- [ ] **步骤 1：先写失败测试**

把下面测试追加到 `backend/tests/agent/test_tools.py` 里现有小红书测试附近：

```python
def test_xhs_guide_keywords_are_strategy_oriented():
    out = xhs_tools._build_xhs_guide_keywords(
        city="顺德",
        days=1,
        travel_style="美食慢游",
        keywords=["避雷", "雨天", "双皮奶"],
    )

    assert out == [
        "顺德旅游攻略",
        "顺德1日游攻略",
        "顺德美食攻略",
        "顺德美食慢游攻略",
        "顺德避雷攻略",
        "顺德雨天攻略",
    ]
    assert all("攻略" in keyword for keyword in out)


@pytest.mark.asyncio
async def test_xhs_search_notes_normalizes_travel_keyword_to_guide_query(monkeypatch):
    calls = []

    async def _fake_run(args):
        calls.append(args)
        return {"ok": True, "data": {"items": []}}

    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)

    out = await tools.xhs_search_notes.ainvoke({
        "keyword": "东京亲子游",
        "sort": "popular",
        "note_type": "image",
        "page": 1,
    })

    assert out["ok"] is True
    assert calls == [[
        "search", "东京亲子游攻略",
        "--sort", "popular",
        "--type", "image",
        "--page", "1",
    ]]
```

- [ ] **步骤 2：运行测试，确认失败**

运行：

```bash
cd backend
uv run pytest tests/agent/test_tools.py::test_xhs_guide_keywords_are_strategy_oriented tests/agent/test_tools.py::test_xhs_search_notes_normalizes_travel_keyword_to_guide_query -q
```

预期：两个测试失败，因为辅助函数尚不存在，`xhs_search_notes` 仍会传原始关键词。

- [ ] **步骤 3：实现关键词辅助函数并接入工具**

在 `backend/app/agent/tools/xhs.py` 的 `_RESEARCH_NOTE_LIMIT` 后加入：

```python
_GUIDE_KEYWORD_LIMIT = 6
_TRAVEL_SEARCH_MARKERS = (
    "旅游", "旅行", "游玩", "亲子", "情侣", "citywalk", "Citywalk",
    "美食", "餐厅", "小吃", "甜品", "咖啡", "景点", "路线",
    "避雷", "拍照", "雨天", "夜市",
)


def _clean_xhs_keyword(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip())


def _ensure_xhs_guide_keyword(city: str, phrase: str = "") -> str:
    city_clean = _clean_xhs_keyword(city)
    phrase_clean = _clean_xhs_keyword(phrase)
    if not city_clean:
        return phrase_clean if "攻略" in phrase_clean else f"{phrase_clean}攻略"
    if not phrase_clean:
        return f"{city_clean}旅游攻略"
    base = phrase_clean if phrase_clean.startswith(city_clean) else f"{city_clean}{phrase_clean}"
    return base if "攻略" in base else f"{base}攻略"


def _build_xhs_guide_keywords(
    city: str,
    days: int,
    travel_style: str,
    keywords: list[str] | None,
    *,
    limit: int = _GUIDE_KEYWORD_LIMIT,
) -> list[str]:
    raw_phrases = ["旅游攻略", f"{days}日游攻略", "美食攻略"]
    if travel_style:
        raw_phrases.append(f"{_clean_xhs_keyword(travel_style)}攻略")
    for keyword in keywords or []:
        cleaned = _clean_xhs_keyword(keyword)
        if cleaned:
            raw_phrases.append(cleaned if "攻略" in cleaned else f"{cleaned}攻略")

    out: list[str] = []
    seen: set[str] = set()
    for phrase in raw_phrases:
        keyword = _ensure_xhs_guide_keyword(city, phrase)
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        out.append(keyword)
        if len(out) >= limit:
            break
    return out


def _normalize_xhs_search_keyword(keyword: str) -> str:
    cleaned = _clean_xhs_keyword(keyword)
    if not cleaned or "攻略" in cleaned:
        return cleaned
    if any(marker in cleaned for marker in _TRAVEL_SEARCH_MARKERS):
        return f"{cleaned}攻略"
    return cleaned
```

把 `research_xhs_travel_guide` 开头的关键词构造替换为：

```python
    keyword_parts = _build_xhs_guide_keywords(
        city=city,
        days=days,
        travel_style=travel_style,
        keywords=keywords or [],
    )
```

把 `xhs_search_notes` 里的 `keyword` 入参接入归一化：

```python
    search_keyword = _normalize_xhs_search_keyword(keyword)
    return await _run_xhs_json([
        "search", search_keyword,
        "--sort", sort,
        "--type", note_type,
        "--page", str(page),
    ])
```

- [ ] **步骤 4：更新参数描述和提示词**

把 `XhsSearchNotesArgs.keyword` 的描述替换为：

```python
    keyword: str = Field(
        description=(
            "小红书搜索关键词。旅行场景优先用攻略型描述，如 顺德旅游攻略、东京亲子游攻略、"
            "成都Citywalk攻略；工具会尽量为旅行关键词补齐“攻略”。"
        )
    )
```

在 `TRIP_AGENT_SYS` 的“小红书用于解释为什么值得去”附近加一条：

```text
- 小红书检索关键词优先写成攻略型描述，如“顺德旅游攻略”“东京亲子游攻略”“成都Citywalk攻略”；避免只搜宽泛词如“顺德美食”。
```

在 `backend/tests/agent/test_prompt.py` 增加：

```python
def test_prompt_prefers_xhs_guide_style_keywords():
    p = TRIP_AGENT_SYS

    for kw in ("攻略型描述", "顺德旅游攻略", "东京亲子游攻略", "避免只搜宽泛词"):
        assert kw in p
```

- [ ] **步骤 5：运行目标测试**

运行：

```bash
cd backend
uv run pytest tests/agent/test_tools.py::test_xhs_guide_keywords_are_strategy_oriented tests/agent/test_tools.py::test_xhs_search_notes_normalizes_travel_keyword_to_guide_query tests/agent/test_prompt.py::test_prompt_prefers_xhs_guide_style_keywords -q
```

预期：全部通过。

- [ ] **步骤 6：提交**

运行：

```bash
git add backend/app/agent/tools/xhs.py backend/app/agent/prompt.py backend/tests/agent/test_tools.py backend/tests/agent/test_prompt.py
git commit -m "feat(xhs): prefer guide-style search keywords"
```

### 任务 2：图片 URL 抽取与多模态笔记解析

**文件：**
- 修改：`backend/app/agent/tools/xhs.py`
- 修改：`backend/tests/agent/test_tools.py`
- 修改：`backend/app/agent/prompt.py`
- 修改：`backend/tests/agent/test_prompt.py`

**接口：**
- 产出：`_extract_xhs_image_urls(value: Any, limit: int = 4) -> list[str]`
- 产出：`_build_xhs_image_messages(target: str, note: dict[str, Any], image_urls: list[str]) -> list[SystemMessage | HumanMessage]`
- 产出：`async def _analyze_xhs_note_images(target: str, note: dict[str, Any], max_images: int = 4) -> dict[str, Any]`
- 产出：`XhsVisualBrief`

- [ ] **步骤 1：先写图片抽取和消息构造测试**

追加到 `backend/tests/agent/test_tools.py`：

```python
def test_extract_xhs_image_urls_prefers_note_images_and_dedupes():
    note = {
        "ok": True,
        "data": {
            "items": [{
                "note_card": {
                    "image_list": [
                        {"url_default": "https://sns-img-qc.xhscdn.com/a.jpg"},
                        {"url_pre": "https://sns-img-qc.xhscdn.com/b.webp?x=1"},
                        {"url": "https://sns-img-qc.xhscdn.com/a.jpg"},
                    ],
                    "cover": "https://sns-img-qc.xhscdn.com/cover.jpg",
                    "user": {"avatar": "https://sns-avatar-qc.xhscdn.com/avatar.jpg"},
                }
            }]
        },
    }

    assert xhs_tools._extract_xhs_image_urls(note, limit=4) == [
        "https://sns-img-qc.xhscdn.com/a.jpg",
        "https://sns-img-qc.xhscdn.com/b.webp?x=1",
        "https://sns-img-qc.xhscdn.com/cover.jpg",
    ]


def test_build_xhs_image_messages_uses_multimodal_blocks():
    messages = xhs_tools._build_xhs_image_messages(
        target="note-1",
        note={"ok": True, "data": {"title": "顺德攻略"}},
        image_urls=["https://sns-img-qc.xhscdn.com/a.jpg"],
    )

    assert len(messages) == 2
    assert "图文解析" in messages[0].content
    assert messages[1].content[0]["type"] == "text"
    assert messages[1].content[1] == {
        "type": "image_url",
        "image_url": {"url": "https://sns-img-qc.xhscdn.com/a.jpg"},
    }
```

- [ ] **步骤 2：运行测试，确认失败**

运行：

```bash
cd backend
uv run pytest tests/agent/test_tools.py::test_extract_xhs_image_urls_prefers_note_images_and_dedupes tests/agent/test_tools.py::test_build_xhs_image_messages_uses_multimodal_blocks -q
```

预期：两个测试失败，因为 helper 尚不存在。

- [ ] **步骤 3：增加图片抽取与视觉数据结构**

在 `backend/app/agent/tools/xhs.py` 的关键词 helper 后加入：

```python
_IMAGE_CONTAINER_KEYS = {
    "image", "images", "image_list", "imageinfo", "image_info",
    "cover", "cover_image", "coverimage",
}
_IMAGE_URL_KEYS = {"url", "url_default", "url_pre", "src", "href"}
_NON_NOTE_IMAGE_HINTS = ("avatar", "profile", "icon", "emoji")

_XHS_IMAGE_SYS = """# 小红书图文解析

## 角色
你是小红书旅行图文解析助手。你会结合笔记正文和图片，提取图片中可见的文字、地点、店名、菜单、价格、时间、路线和避雷线索。

## 约束
- 只提取图片和正文能支持的信息，不要凭常识补全。
- 忽略头像、水印、表情和无关装饰图。
- 看不清或不确定时把 confidence 设为 low，并在 warnings 中说明。
- 输出短句，适合后续旅行研究摘要归纳和高德检索。
"""


class XhsVisualBrief(BaseModel):
    target: str = Field(description="笔记目标 ID 或 URL。")
    image_count: int = Field(default=0, ge=0, description="实际送入视觉模型的图片数量。")
    visible_text: list[str] = Field(default_factory=list, description="图片中可见的短文字，如店名、菜单、价格、营业时间。")
    places: list[str] = Field(default_factory=list, description="图片或正文能支持的地点、店铺、街区名称。")
    foods: list[str] = Field(default_factory=list, description="图片或正文能支持的菜品、小吃、饮品关键词。")
    route_or_time_clues: list[str] = Field(default_factory=list, description="图片中出现的路线、时间段、排队或预约线索。")
    tips: list[str] = Field(default_factory=list, description="可用于攻略的注意事项。")
    confidence: Literal["high", "medium", "low"] = Field(default="medium", description="整体视觉解析置信度。")
    warnings: list[str] = Field(default_factory=list, description="解析限制或失败原因。")
    image_urls: list[str] = Field(default_factory=list, description="参与解析的图片 URL。")


def _is_xhs_image_url(value: str) -> bool:
    text = value.strip()
    if not text.lower().startswith(("http://", "https://")):
        return False
    lowered = text.lower()
    if any(hint in lowered for hint in _NON_NOTE_IMAGE_HINTS):
        return False
    if lowered.endswith((".mp4", ".mov", ".m3u8")):
        return False
    return True


def _extract_xhs_image_urls(value: Any, *, limit: int = 4) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add_url(raw: str) -> None:
        if len(urls) >= limit:
            return
        cleaned = raw.strip()
        if not _is_xhs_image_url(cleaned) or cleaned in seen:
            return
        seen.add(cleaned)
        urls.append(cleaned)

    def walk(node: Any, *, in_image_container: bool = False) -> None:
        if len(urls) >= limit:
            return
        if isinstance(node, str):
            if in_image_container:
                add_url(node)
            return
        if isinstance(node, dict):
            for key, child in node.items():
                key_l = str(key).lower()
                next_in_image = (
                    in_image_container
                    or key_l in _IMAGE_CONTAINER_KEYS
                    or "image_list" in key_l
                    or "cover" in key_l
                )
                if next_in_image and key_l in _IMAGE_URL_KEYS and isinstance(child, str):
                    add_url(child)
                walk(child, in_image_container=next_in_image)
        elif isinstance(node, list):
            for child in node:
                walk(child, in_image_container=in_image_container)
                if len(urls) >= limit:
                    break

    walk(value)
    return urls


def _build_xhs_image_messages(
    target: str,
    note: dict[str, Any],
    image_urls: list[str],
) -> list[SystemMessage | HumanMessage]:
    note_text = _compact_json(note, limit=1800)
    blocks: list[dict[str, Any]] = [{
        "type": "text",
        "text": (
            "请解析这篇小红书旅行笔记的图文信息。"
            f"\n目标: {target}"
            f"\n笔记JSON摘要: {note_text}"
            "\n重点提取图片中出现的地点、店名、菜单、价格、营业时间、路线、排队和避雷线索。"
        ),
    }]
    for url in image_urls:
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return [
        SystemMessage(content=_XHS_IMAGE_SYS),
        HumanMessage(content=blocks),
    ]
```

- [ ] **步骤 4：增加多模态 LLM 辅助函数和降级路径**

在 `_build_xhs_image_messages` 后加入：

```python
async def _analyze_xhs_note_images(
    target: str,
    note: dict[str, Any],
    *,
    max_images: int = 4,
) -> dict[str, Any]:
    image_urls = _extract_xhs_image_urls(note, limit=max(0, min(max_images, 6)))
    if not image_urls:
        return XhsVisualBrief(
            target=target,
            image_count=0,
            confidence="low",
            warnings=["xhs_note_has_no_extractable_images"],
            image_urls=[],
        ).model_dump()

    try:
        llm = build_llm(temperature=0, disable_streaming=True).with_structured_output(
            XhsVisualBrief,
            method="function_calling",
        )
        result = await llm.ainvoke(_build_xhs_image_messages(target, note, image_urls))
        data = result.model_dump() if isinstance(result, BaseModel) else dict(result)
        data["target"] = data.get("target") or target
        data["image_count"] = len(image_urls)
        data["image_urls"] = image_urls
        return data
    except Exception:
        return XhsVisualBrief(
            target=target,
            image_count=len(image_urls),
            confidence="low",
            warnings=["xhs_image_analysis_failed"],
            image_urls=image_urls,
        ).model_dump()
```

- [ ] **步骤 5：更新小红书研究 prompt**

在 `XHS_RESEARCH_SYS` 的 `## 提取重点` 下加入：

```text
- 图片解析结果中的店名、菜单、价格、营业时间、路线图、排队和避雷线索；图片信息只能作为待校验线索。
```

在 `## 处理原则` 下加入：

```text
- 图中文字或画面不清楚时，不要当作确定事实；必须在 tips 或 reason 中体现不确定性。
```

在 `backend/tests/agent/test_prompt.py` 增加：

```python
def test_xhs_research_prompt_mentions_image_text_analysis():
    p = XHS_RESEARCH_SYS

    for kw in ("图片解析结果", "店名", "菜单", "营业时间", "待校验线索", "不确定性"):
        assert kw in p
```

- [ ] **步骤 6：运行目标测试**

运行：

```bash
cd backend
uv run pytest tests/agent/test_tools.py::test_extract_xhs_image_urls_prefers_note_images_and_dedupes tests/agent/test_tools.py::test_build_xhs_image_messages_uses_multimodal_blocks tests/agent/test_prompt.py::test_xhs_research_prompt_mentions_image_text_analysis -q
```

预期：全部通过。

- [ ] **步骤 7：提交**

运行：

```bash
git add backend/app/agent/tools/xhs.py backend/app/agent/prompt.py backend/tests/agent/test_tools.py backend/tests/agent/test_prompt.py
git commit -m "feat(xhs): parse note images with multimodal llm"
```

### 任务 3：把图文解析接入小红书工具和旅行研究摘要

**文件：**
- 修改：`backend/app/agent/tools/xhs.py`
- 修改：`backend/tests/agent/test_tools.py`

**接口：**
- 新增：`class XhsReadNoteArgs(XhsReadTargetArgs)`，包含 `analyze_images: bool = True` 和 `max_images: int = 4`
- 修改：`XhsTravelResearchArgs` 增加 `analyze_images: bool = True` 和 `max_images_per_note: int = 4`
- 修改：`XhsTravelBrief` 增加 `visual_clues: list[str]`
- 修改：`xhs_read_note(target: str, analyze_images: bool = True, max_images: int = 4) -> dict[str, Any]`
- 修改：`research_xhs_travel_guide(..., analyze_images: bool = True, max_images_per_note: int = 4) -> dict[str, Any]`

- [ ] **步骤 1：写 `xhs_read_note` 附加图文解析的失败测试**

追加到 `backend/tests/agent/test_tools.py`：

```python
@pytest.mark.asyncio
async def test_xhs_read_note_adds_image_analysis_without_changing_envelope(monkeypatch):
    calls = []

    async def _fake_run(args):
        calls.append(args)
        return {
            "ok": True,
            "data": {
                "items": [{
                    "note_card": {
                        "title": "顺德攻略",
                        "image_list": [{"url_default": "https://sns-img-qc.xhscdn.com/a.jpg"}],
                    }
                }]
            },
        }

    async def _fake_analyze(target, note, *, max_images):
        assert target == "note-1"
        assert max_images == 2
        assert note["ok"] is True
        return {
            "target": target,
            "image_count": 1,
            "visible_text": ["清晖园 09:00"],
            "places": ["清晖园"],
            "foods": [],
            "route_or_time_clues": ["09:00 人少"],
            "tips": [],
            "confidence": "high",
            "warnings": [],
            "image_urls": ["https://sns-img-qc.xhscdn.com/a.jpg"],
        }

    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)
    monkeypatch.setattr(xhs_tools, "_analyze_xhs_note_images", _fake_analyze)

    out = await tools.xhs_read_note.ainvoke({
        "target": "note-1",
        "analyze_images": True,
        "max_images": 2,
    })

    assert out["ok"] is True
    assert out["data"]["items"][0]["note_card"]["title"] == "顺德攻略"
    assert out["image_analysis"]["places"] == ["清晖园"]
    assert out["meta"]["image_analysis"]["attempted"] is True
    assert out["meta"]["image_analysis"]["image_count"] == 1
    assert calls == [["read", "note-1"]]
```

- [ ] **步骤 2：写旅行研究载荷包含图文解析的失败测试**

追加到 `backend/tests/agent/test_tools.py`：

```python
@pytest.mark.asyncio
async def test_research_xhs_travel_guide_includes_image_analysis_in_brief_payload(monkeypatch):
    run_calls = []
    llm_calls = []

    async def _fake_run(args):
        run_calls.append(args)
        if args[0] == "search":
            return {"ok": True, "data": {"items": [{"note_id": "note-1"}]}}
        if args[0] == "read":
            return {
                "ok": True,
                "data": {
                    "items": [{
                        "note_card": {
                            "title": "顺德旅游攻略",
                            "desc": "正文提到清晖园。",
                            "image_list": [{"url_default": "https://sns-img-qc.xhscdn.com/a.jpg"}],
                        }
                    }]
                },
            }
        return {"ok": True, "data": {}}

    async def _fake_analyze(target, note, *, max_images):
        return {
            "target": target,
            "image_count": 1,
            "visible_text": ["清晖园 09:00"],
            "places": ["清晖园"],
            "foods": ["双皮奶"],
            "route_or_time_clues": ["上午人少"],
            "tips": ["图片信息待地图校验"],
            "confidence": "high",
            "warnings": [],
            "image_urls": ["https://sns-img-qc.xhscdn.com/a.jpg"],
        }

    brief = xhs_tools.XhsTravelBrief(
        city="顺德",
        summary="图片和正文都支持上午去清晖园。",
        visual_clues=["图片文字显示清晖园 09:00"],
        amap_query_hints=["清晖园", "双皮奶"],
    )

    class _CaptureRunnable:
        async def ainvoke(self, messages, **_kwargs):
            llm_calls.append(messages)
            return brief

    class _CaptureLLM:
        def with_structured_output(self, *_args, **_kwargs):
            return _CaptureRunnable()

    monkeypatch.setattr(xhs_tools, "_run_xhs_json", _fake_run)
    monkeypatch.setattr(xhs_tools, "_analyze_xhs_note_images", _fake_analyze)
    monkeypatch.setattr(xhs_tools, "build_llm", lambda *_a, **_k: _CaptureLLM())

    out = await tools.research_xhs_travel_guide.ainvoke({
        "city": "顺德",
        "days": 1,
        "travel_style": "",
        "keywords": [],
        "max_notes": 1,
        "include_comments": False,
        "analyze_images": True,
        "max_images_per_note": 1,
    })

    payload = json.loads(llm_calls[0][1].content)
    assert payload["notes"][0]["image_analysis"]["places"] == ["清晖园"]
    assert payload["notes"][0]["image_analysis"]["foods"] == ["双皮奶"]
    assert out["data"]["visual_clues"] == ["图片文字显示清晖园 09:00"]
    assert out["meta"]["image_analysis_count"] == 1
    assert run_calls[0] == ["search", "顺德旅游攻略", "--sort", "popular", "--type", "all", "--page", "1"]
```

- [ ] **步骤 3：运行测试，确认失败**

运行：

```bash
cd backend
uv run pytest tests/agent/test_tools.py::test_xhs_read_note_adds_image_analysis_without_changing_envelope tests/agent/test_tools.py::test_research_xhs_travel_guide_includes_image_analysis_in_brief_payload -q
```

预期：两个测试失败，因为参数结构和集成字段还不存在。

- [ ] **步骤 4：扩展参数结构**

保留 `XhsReadTargetArgs` 只负责通用 `target`，避免 `xhs_note_comments` 继承图片解析参数。新增：

```python
class XhsReadNoteArgs(XhsReadTargetArgs):
    """Read a Xiaohongshu note and optionally analyze images."""

    analyze_images: bool = Field(
        default=True,
        description="是否用多模态 LLM 解析笔记图片，默认开启以覆盖图文攻略中的图片信息。",
    )
    max_images: int = Field(default=4, ge=0, le=6, description="最多解析多少张笔记图片。")
```

把 `xhs_read_note` 的装饰器改为：

```python
@tool(args_schema=XhsReadNoteArgs)
```

在 `XhsTravelResearchArgs` 中加入：

```python
    analyze_images: bool = Field(default=True, description="是否解析攻略笔记中的图片信息。")
    max_images_per_note: int = Field(default=4, ge=0, le=6, description="每篇笔记最多解析多少张图片。")
```

在 `XhsTravelBrief` 中加入：

```python
    visual_clues: list[str] = Field(default_factory=list, description="从图片解析得到、仍需地图或正文校验的短线索。")
```

- [ ] **步骤 5：替换 `xhs_read_note` 实现**

把当前 `xhs_read_note` 函数替换为：

```python
@tool(args_schema=XhsReadNoteArgs)
async def xhs_read_note(
    target: str,
    analyze_images: bool = True,
    max_images: int = 4,
) -> dict[str, Any]:
    """读取小红书笔记详情。默认额外解析图文笔记中的图片信息，target 应来自搜索结果、用户粘贴 URL 或真实 note_id。"""
    result = await _run_xhs_json(["read", target])
    if analyze_images and max_images > 0 and result.get("ok") is not False:
        analysis = await _analyze_xhs_note_images(target, result, max_images=max_images)
        result = dict(result)
        result["image_analysis"] = analysis
        meta = dict(result.get("meta") or {})
        meta["image_analysis"] = {
            "attempted": True,
            "image_count": int(analysis.get("image_count", 0)),
            "warnings": list(analysis.get("warnings", [])),
        }
        result["meta"] = meta
    return result
```

- [ ] **步骤 6：替换 `research_xhs_travel_guide` 签名和笔记读取循环**

把函数签名改为：

```python
async def research_xhs_travel_guide(
    city: str,
    days: int = 1,
    travel_style: str = "",
    keywords: list[str] | None = None,
    max_notes: int = 4,
    include_comments: bool = False,
    analyze_images: bool = True,
    max_images_per_note: int = 4,
) -> dict[str, Any]:
```

把笔记读取循环替换为：

```python
    notes = []
    image_analysis_count = 0
    for target in targets[:max_notes]:
        note = await _run_xhs_json(["read", target])
        note_payload: dict[str, Any] = {"target": target, "note": note}
        if analyze_images and max_images_per_note > 0 and note.get("ok") is not False:
            image_analysis = await _analyze_xhs_note_images(
                target,
                note,
                max_images=max_images_per_note,
            )
            note_payload["image_analysis"] = image_analysis
            if image_analysis.get("image_count", 0):
                image_analysis_count += 1
        if include_comments and note.get("ok") is not False:
            note_payload["comments"] = await _run_xhs_json(["comments", target])
        notes.append(note_payload)
```

在载荷的 `notes` 列表元素里加入：

```python
                "image_analysis": item.get("image_analysis", {}),
```

在返回值 `meta` 中加入：

```python
            "analyze_images": analyze_images,
            "image_analysis_count": image_analysis_count,
            "max_images_per_note": max_images_per_note,
```

- [ ] **步骤 7：更新既有研究测试**

在 `test_research_xhs_travel_guide_extracts_structured_brief` 的 invoke 参数中加入：

```python
        "analyze_images": False,
```

这样旧测试继续聚焦“搜索、读取、评论、结构化研究摘要”，不会额外计算图片解析调用次数。

- [ ] **步骤 8：运行目标测试**

运行：

```bash
cd backend
uv run pytest tests/agent/test_tools.py::test_xhs_read_note_adds_image_analysis_without_changing_envelope tests/agent/test_tools.py::test_research_xhs_travel_guide_includes_image_analysis_in_brief_payload tests/agent/test_tools.py::test_research_xhs_travel_guide_extracts_structured_brief -q
```

预期：全部通过。

- [ ] **步骤 9：提交**

运行：

```bash
git add backend/app/agent/tools/xhs.py backend/tests/agent/test_tools.py
git commit -m "feat(xhs): include visual clues in travel research"
```

### 任务 4：验证与项目记录

**文件：**
- 修改：`backend/tests/agent/test_tools.py`
- 修改：`backend/tests/agent/test_prompt.py`
- 修改：`plan/20260628_xhs_multimodal_guide_search/README.md`

**接口：**
- 消费：任务 1-3 的全部改动
- 产出：目标测试通过、后端套件状态明确、`plan/` 记录完整

- [ ] **步骤 1：运行小红书和 prompt 相关测试**

运行：

```bash
cd backend
uv run pytest tests/agent/test_tools.py tests/agent/test_prompt.py tests/agent/test_build_agent.py -q
```

预期：全部通过。

- [ ] **步骤 2：运行更完整的后端测试**

运行：

```bash
cd backend
uv run pytest -q
```

预期：测试套件通过；如果存在失败，必须记录失败文件、测试名、断言信息，并确认是否与本次小红书改动有关。没有这条命令的成功输出，不能声称后端全绿。

- [ ] **步骤 3：可选真实联调**

仅在本机 `xhs status --json` 已登录时运行：

```bash
cd backend
uv run xhs status --json
uv run python - <<'PY'
import asyncio
from app.agent.tools.xhs import research_xhs_travel_guide

async def main():
    out = await research_xhs_travel_guide.ainvoke({
        "city": "顺德",
        "days": 1,
        "keywords": ["避雷"],
        "max_notes": 1,
        "include_comments": False,
        "analyze_images": True,
        "max_images_per_note": 2,
    })
    print(out["ok"])
    print(out["meta"]["search_keywords"])
    print(out["meta"]["image_analysis_count"])

asyncio.run(main())
PY
```

预期：第一个搜索词是 `顺德旅游攻略`；工具返回 `ok=True`；`image_analysis_count` 依据真实笔记图片和模型可用性为 `0` 或 `1`。

- [ ] **步骤 4：更新 `plan/` 记录**

把 `plan/20260628_xhs_multimodal_guide_search/README.md` 替换为：

```markdown
# 任务目标

升级小红书旅行研究能力：检索关键词默认使用攻略型描述，并对图文笔记中的图片做多模态 LLM 解析，避免遗漏图片里的店名、路线、菜单、价格、时间和避雷信息。

# 改动文件

- `backend/app/agent/tools/xhs.py`
- `backend/app/agent/prompt.py`
- `backend/tests/agent/test_tools.py`
- `backend/tests/agent/test_prompt.py`

# 改动详情

- 新增攻略型关键词生成和普通旅行关键词补齐逻辑，让旅行检索优先走 `目的地 + 攻略` 查询。
- 新增小红书笔记图片 URL 抽取，覆盖 `note_card.image_list`、`images`、`cover` 等常见结构。
- 新增多模态图文解析辅助函数，使用现有 `build_llm` 和 LangChain 多模态消息块，不引入新依赖。
- `xhs_read_note` 默认在原始 CLI 响应外壳之外附加 `image_analysis` 和 `meta.image_analysis`。
- `research_xhs_travel_guide` 默认把每篇笔记的图片解析结果纳入最终旅行研究摘要输入，并在输出中提供 `visual_clues`。
- 图文解析失败时返回警告并继续文本研究，不阻断旅行规划。
- 更新系统提示，要求小红书检索使用攻略型关键词，并将图片解析结果视为待地图/正文校验的线索。

# 测试结果

执行完成后记录以下命令的真实输出摘要：

- `cd backend && uv run pytest tests/agent/test_tools.py tests/agent/test_prompt.py tests/agent/test_build_agent.py -q`
- `cd backend && uv run pytest -q`

# 相关讨论

- 小红书工具继续保持只读边界，不接入发布、点赞、收藏或评论等账号写操作。
- 图片解析结果只作为攻略研究线索，最终地点、地址和坐标仍需高德校验。
- 默认最多解析每篇笔记 4 张图，避免成本和上下文膨胀。
```

- [ ] **步骤 5：提交记录**

运行：

```bash
git add plan/20260628_xhs_multimodal_guide_search/README.md
git commit -m "docs(xhs): record multimodal guide search upgrade"
```

## 自检

- 覆盖用户两个问题：小红书图文笔记多模态解析、攻略型关键词检索。
- 贴合现有架构：保留 `xiaohongshu-cli`，在现有 `xhs.py` 扩展，不另起一套集成。
- 失败路径明确：图文解析失败只产生警告，不阻断搜索和文本研究摘要。
- 测试可控：所有测试都通过 monkeypatch 打桩，不依赖真实小红书登录或外部 LLM。
- 范围克制：无需改前端，因为本次能力在后端 agent 工具和提示词层生效。
