"""preflight 可行性闸门：op 声明依赖 → 确定性校验 → 补救 → 裁决。

裁决三态（设计 §6）：
- 全部满足 → operations 原样（含补救后的 requirements_patch）放行。
- 缺信息但**可由用户补**（如 city）→ 进 blocked + 给 clarification，understand 节点据此 interrupt 反问。
- 缺信息且**不可由用户即时补**（如 day 不存在 / 缺 amount）→ 进 blocked、不给 clarification，交 render 诚实回报。

判定全部是确定性代码；LLM 不参与（understand 节点只负责把 clarification 转成自然语言反问，本模块已给出可直接用的中文反问句）。
"""
import re

from pydantic import BaseModel, Field

# op → 依赖键列表。键语义见 _check 内部判定。
OP_REQUIREMENTS: dict[str, list[str]] = {
    "replace_plan": ["city", "days"],
    "set_region": ["city", "area", "day_exists"],
    "add_poi": ["day_exists"],
    "replace_poi": ["day_exists"],
    "remove_poi": ["day_exists"],
    "reorder": ["day_exists"],
    "set_pace": ["day_exists"],
    "set_budget": ["amount"],
    "set_hotel": ["overnight_exists"],
    "answer_only": [],
}

# 缺失这些键时可走 interrupt 反问用户补；其余缺失只能 render 回报。
_USER_FILLABLE = {"city", "days"}

_CITY_RE = re.compile(r"([一-龥]{2,4})(?:市|区)?")


class PreflightResult(BaseModel):
    operations: list[dict] = Field(default_factory=list)
    blocked: list[dict] = Field(default_factory=list)     # [{index, op, missing:[...], reason}]
    clarification: str = ""                                # 需 interrupt 反问的中文句；无则空


def infer_city(state: dict) -> str:
    """确定性反推城市：normalized_req.city → 顶层 city → 会话摘要里的城市名。推不出返回 ""。"""
    req = state.get("normalized_req", {}) or {}
    city = (req.get("city") or state.get("city") or "").strip()
    if city:
        return city
    summary = state.get("conversation_summary", "") or ""
    m = _CITY_RE.search(summary)
    return m.group(1) if m else ""


def _day_exists(state: dict, day) -> bool:
    return any(d.get("day") == day for d in (state.get("day_plans") or []))


def _overnight_exists(state: dict) -> bool:
    return len(state.get("day_plans") or []) > 1


def _check(op: dict, state: dict) -> tuple[list[str], dict]:
    """返回 (缺失键列表, 该 op 的 requirements_patch 补救增量)。"""
    kind = op.get("op")
    missing: list[str] = []
    patch = dict(op.get("requirements_patch") or {})
    for need in OP_REQUIREMENTS.get(kind, []):
        if need == "city":
            city = (patch.get("city") or "").strip() or infer_city(state)
            if city:
                patch["city"] = city
            else:
                missing.append("city")
        elif need == "days":
            days = patch.get("days") or (state.get("normalized_req", {}) or {}).get("days")
            if days:
                patch["days"] = days
            else:
                missing.append("days")
        elif need == "area":
            if not (op.get("area") or "").strip():
                missing.append("area")
        elif need == "day_exists":
            if not _day_exists(state, op.get("day")):
                missing.append("day_exists")
        elif need == "amount":
            if op.get("amount") is None:
                missing.append("amount")
        elif need == "overnight_exists":
            if not _overnight_exists(state):
                missing.append("overnight_exists")
    return missing, patch


def _clarify_sentence(op: dict, missing: list[str]) -> str:
    if "city" in missing:
        area = (op.get("area") or "").strip()
        tail = f"把第{op.get('day')}天改到「{area}」" if area else "重新规划"
        return f"我不确定当前是哪个城市，没法{tail}，方便告诉我城市吗？"
    if "days" in missing:
        return "你想安排几天的行程呢？"
    return ""


def preflight(operations: list[dict], state: dict) -> PreflightResult:
    out_ops: list[dict] = []
    blocked: list[dict] = []
    clarification = ""
    for i, op in enumerate(operations):
        missing, patch = _check(op, state)
        new_op = {**op, "requirements_patch": patch}
        out_ops.append(new_op)
        if missing:
            blocked.append({"index": i, "op": op.get("op"), "missing": missing,
                            "reason": "缺少必要信息：" + "、".join(missing)})
            if not clarification and any(m in _USER_FILLABLE for m in missing):
                clarification = _clarify_sentence(op, missing)
    return PreflightResult(operations=out_ops, blocked=blocked, clarification=clarification)
