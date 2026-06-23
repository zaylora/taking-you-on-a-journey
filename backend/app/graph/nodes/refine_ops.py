"""refine 可组合原子操作的结构化 schema（LLM 解析产出 → state['refine_request']）。

扁平 Operation 模型：所有字段可选 + op 字面量。执行器侧按 op 校验必填字段，
缺失即视为该 op 解析失败并跳过（见 refine 节点）。选用扁平模型而非 discriminated
union，是因为跨 provider 的 function-calling 对联合类型支持不稳。
"""
from typing import Literal

from pydantic import BaseModel, Field


class Selector(BaseModel):
    """remove_poi / replace_poi 的目标项定位器。"""
    by: Literal["name", "ordinal"] = "name"
    name: str = Field(default="", description="按名字模糊匹配（item.name 包含该串）")
    kind: Literal["attraction", "meal"] = Field(default="attraction", description="按序号定位时的项类型")
    index: int = Field(default=-1, description="按序号定位：同类项中的序号，-1 表示最后一个")


class Operation(BaseModel):
    op: Literal[
        "set_region", "add_poi", "remove_poi", "replace_poi",
        "reorder", "set_pace", "set_budget", "set_hotel",
    ] = Field(description="原子操作类型；决定本条其余字段的语义")
    day: int | None = Field(default=None, description="目标天（从 1 开始）；全局操作可为空")
    area: str = Field(default="", description="set_region：新区域地名，如「黄埔」")
    query: str = Field(default="", description="add_poi/replace_poi/set_region：检索关键词")
    kind: Literal["attraction", "meal"] = Field(default="attraction", description="add_poi/replace_poi：新增/替换的项类型")
    selector: Selector | None = Field(default=None, description="remove_poi/replace_poi：要操作的目标项")
    strategy: Literal["optimize", "reverse"] = Field(default="optimize", description="reorder：optimize=就近重排，reverse=倒序")
    direction: Literal["relax", "tighten"] = Field(default="relax", description="set_pace：relax/tighten 均做删减至时间预算内")
    amount: float | None = Field(default=None, description="set_budget：新预算上限(元)")
    days: list[int] | None = Field(default=None, description="set_hotel：目标过夜日；空=全部过夜日")
    criteria: str = Field(default="", description="set_hotel：偏好描述，如「离地铁近」")


class RefinePlan(BaseModel):
    operations: list[Operation] = Field(default_factory=list, description="按用户语序排列的原子操作")
    clarification: str | None = Field(default=None, description="无法解析出任何操作时，向用户反问的一句话")
