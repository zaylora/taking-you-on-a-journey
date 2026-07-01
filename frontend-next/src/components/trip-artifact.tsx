"use client";

import { ChevronLeft, MapPinned, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AmapView } from "@/components/amap-view";
import type { DayPlan, TripItem, TripUiState } from "@/lib/types";
import { cn } from "@/lib/utils";

interface TripArtifactProps {
  state: TripUiState;
  onClose: () => void;
  onSelectDay: (day: number | null) => void;
  onSelectPoi: (poiId: string | null) => void;
}

export function TripArtifact({
  state,
  onClose,
  onSelectDay,
  onSelectPoi,
}: TripArtifactProps) {
  const visibleDays =
    state.activeDay === null
      ? state.dayPlans
      : state.dayPlans.filter((day) => day.day === state.activeDay);

  return (
    <aside
      aria-label="行程工作区"
      className={cn(
        "relative flex h-full w-full max-w-[760px] flex-col border-l border-zinc-200 bg-white shadow-2xl transition-transform",
        state.artifactOpen ? "translate-x-0" : "translate-x-full",
      )}
    >
      <header className="flex h-14 items-center justify-between border-b border-zinc-200 px-4">
        <div className="flex min-w-0 items-center gap-2">
          <MapPinned className="h-4 w-4 text-zinc-600" />
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-zinc-950">
              行程地图
            </h2>
            <p className="text-xs text-zinc-500">
              {state.dayPlans.length
                ? `${state.dayPlans.length} 天路线`
                : "等待生成结果"}
            </p>
          </div>
        </div>
        <Button type="button" variant="ghost" size="icon" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </header>

      <div className="grid min-h-0 flex-1 grid-rows-[minmax(260px,42vh)_1fr]">
        <div className="relative bg-zinc-100">
          <AmapView
            dayPlans={state.dayPlans}
            activeDay={state.activeDay}
            activePoiId={state.activePoiId}
            onSelectPoi={onSelectPoi}
          />
        </div>

        <div className="min-h-0 overflow-y-auto p-4">
          {state.budget?.estimated ? (
            <div className="mb-4 rounded-md border border-zinc-200 bg-zinc-50 p-3 text-sm">
              <span className="font-medium text-zinc-950">
                预计 ¥{Math.round(state.budget.estimated)}
              </span>
              {state.budget.limit ? (
                <span className="text-zinc-500"> / 预算 ¥{state.budget.limit}</span>
              ) : null}
            </div>
          ) : null}

          <div className="mb-4 flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant={state.activeDay === null ? "default" : "outline"}
              onClick={() => onSelectDay(null)}
            >
              总览
            </Button>
            {state.dayPlans.map((day) => (
              <Button
                key={day.day}
                type="button"
                size="sm"
                variant={state.activeDay === day.day ? "default" : "outline"}
                onClick={() => onSelectDay(day.day)}
              >
                Day {day.day}
              </Button>
            ))}
          </div>

          <div className="space-y-5">
            {visibleDays.map((day) => (
              <DayRoute
                key={day.day}
                day={day}
                activePoiId={state.activePoiId}
                onSelectPoi={onSelectPoi}
              />
            ))}
          </div>
        </div>
      </div>

      <Button
        type="button"
        variant="outline"
        size="icon"
        className="absolute left-0 top-16 hidden -translate-x-1/2 bg-white lg:inline-flex"
        onClick={onClose}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
    </aside>
  );
}

function DayRoute({
  day,
  activePoiId,
  onSelectPoi,
}: {
  day: DayPlan;
  activePoiId: string | null;
  onSelectPoi: (poiId: string | null) => void;
}) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-zinc-950">Day {day.day}</h3>
        {day.weather?.text ? <Badge>{day.weather.text}</Badge> : null}
        {day.weather?.temp ? <span className="text-xs text-zinc-500">{day.weather.temp}</span> : null}
      </div>
      <div className="space-y-2">
        {day.items
          .filter((item) => item.type === "transport" || item.name)
          .map((item, index) => (
            <RouteItem
              key={item.poi_id ?? `${item.type}-${index}`}
              item={item}
              active={Boolean(item.poi_id && item.poi_id === activePoiId)}
              onSelectPoi={onSelectPoi}
            />
          ))}
        {day.hotel ? (
          <button
            type="button"
            onClick={() => onSelectPoi(day.hotel?.poi_id ?? null)}
            className={cn(
              "flex w-full items-start gap-3 rounded-md border border-zinc-200 bg-zinc-50 p-3 text-left text-sm",
              activePoiId === day.hotel.poi_id && "border-zinc-950",
            )}
          >
            <span>酒店</span>
            <span className="font-medium text-zinc-950">{day.hotel.name}</span>
          </button>
        ) : null}
      </div>
    </section>
  );
}

function RouteItem({
  item,
  active,
  onSelectPoi,
}: {
  item: TripItem;
  active: boolean;
  onSelectPoi: (poiId: string | null) => void;
}) {
  if (item.type === "transport") {
    return (
      <div className="rounded-md border border-dashed border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-500">
        {item.from && item.to ? `${item.from} -> ${item.to}` : item.mode ?? "交通"}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onSelectPoi(item.poi_id ?? null)}
      className={cn(
        "flex w-full items-start justify-between gap-3 rounded-md border border-zinc-200 bg-white p-3 text-left text-sm transition hover:border-zinc-400",
        active && "border-zinc-950 shadow-sm",
      )}
    >
      <span className="min-w-0">
        <span className="block truncate font-medium text-zinc-950">
          {item.name}
        </span>
        <span className="text-xs text-zinc-500">
          {item.type === "meal" ? "餐饮" : "景点"}
          {item.cost ? ` · ¥${item.cost}` : ""}
        </span>
      </span>
      {item.indoor ? <Badge>室内</Badge> : null}
    </button>
  );
}
