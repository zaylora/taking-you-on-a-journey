# -*- coding: utf-8 -*-
"""itinerary 结构化输出数据类（LLM 软填 + 下游消费契约）。"""
from pydantic import BaseModel, Field



class Location(BaseModel):
    lng: float = Field(default=0.0, description="经度，沿用输入坐标，不要自行编造")
    lat: float = Field(default=0.0, description="纬度，沿用输入坐标，不要自行编造")


class DayWeather(BaseModel):
    text: str = Field(default="", description="天气描述，如“晴”“小雨”；沿用输入天气数据")
    temp: str = Field(default="", description="气温，如“18~26℃”；沿用输入天气数据")
    is_rainy: bool = Field(default=False, description="当天是否下雨，下雨时应优先安排室内项")


class PlanItem(BaseModel):
    type: str = Field(
        description="行程项类型，仅限三种：attraction（景点）、meal（餐饮）、transport（交通）"
    )
    name: str = Field(default="", description="景点或餐厅名称；transport 项可留空")
    poi_id: str = Field(default="", description="高德 POI id，沿用输入数据，不要编造")
    location: Location = Field(default_factory=Location, description="该项经纬度，沿用输入坐标")
    start: str = Field(default="", description="开始时间，24 小时制 HH:MM，如 09:30")
    end: str = Field(default="", description="结束时间，24 小时制 HH:MM，如 11:30")
    indoor: bool = Field(default=False, description="是否室内项；雨天优先安排 indoor=true 的项")
    note: str = Field(default="", description="补充说明，一句话简述安排理由或注意事项")
    mode: str = Field(default="", description="交通方式，如“步行”“地铁”“驾车”；仅 transport 项填写")
    from_: str = Field(default="", alias="from", description="交通出发地名称；仅 transport 项填写")
    to: str = Field(default="", description="交通目的地名称；仅 transport 项填写")
    cost: float = Field(default=0.0, description="该项人均花费(元)：门票/餐标/市内交通；免费景点或交通项填 0")

    model_config = {"populate_by_name": True}


class Hotel(BaseModel):
    name: str = Field(default="", description="酒店名称，沿用候选池，不要编造")
    poi_id: str = Field(default="", description="高德 POI id；降级参考酒店可留空")
    location: Location = Field(default_factory=Location, description="酒店经纬度")
    price: float = Field(default=0.0, description="每晚整间价(元)，按住宿档位估")
    level: str = Field(default="", description="住宿档位：经济/舒适/高端")


class DayPlan(BaseModel):
    day: int = Field(description="第几天，从 1 开始的正整数")
    date: str = Field(default="", description="当天日期，格式 YYYY-MM-DD；由 start_date 顺延推算")
    weather: DayWeather = Field(default_factory=DayWeather, description="当天天气，沿用输入天气数据")
    center: Location = Field(default_factory=Location, description="当天活动的中心坐标")
    items: list[PlanItem] = Field(
        default_factory=list,
        description="当天按时间顺序排列的行程项，含景点、餐饮与必要的市内交通",
    )
    hotel: Hotel | None = Field(default=None, description="当晚住宿；离程日/单日游为 None")


class DayPlans(BaseModel):
    days: list[DayPlan] = Field(
        default_factory=list, description="逐天的行程安排列表，长度应等于总天数 days"
    )


