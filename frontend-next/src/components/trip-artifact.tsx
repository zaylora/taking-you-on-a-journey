"use client";

import {
  CopyIcon,
  DownloadIcon,
  MapPinned,
  RefreshCwIcon,
} from "lucide-react";

import { AmapView } from "@/components/amap-view";
import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactClose,
  ArtifactContent,
  ArtifactDescription,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
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
  const routeDescription = state.dayPlans.length
    ? `${state.dayPlans.length} 天路线`
    : "等待生成结果";

  return (
    <aside
      aria-label="行程工作区"
      className="flex h-full w-full justify-end"
    >
      <Artifact
        data-testid="ai-elements-artifact"
        className={cn(
          "h-full w-full max-w-[820px] rounded-none border-y-0 border-r-0 bg-background shadow-2xl",
          "animate-in slide-in-from-right-8 fade-in-0 duration-500 ease-out",
        )}
      >
        <ArtifactHeader className="h-16 shrink-0 bg-muted/40">
          <div className="flex min-w-0 items-center gap-3">
            <ArtifactClose onClick={onClose} aria-label="关闭行程工作区" />
            <div className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-background">
              <MapPinned className="size-4 text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <ArtifactTitle className="truncate" role="heading" aria-level={2}>
                行程地图
              </ArtifactTitle>
              <ArtifactDescription>{routeDescription}</ArtifactDescription>
            </div>
          </div>

          <ArtifactActions>
            <ArtifactAction
              icon={RefreshCwIcon}
              label="刷新路线"
              tooltip="刷新路线"
            />
            <ArtifactAction icon={CopyIcon} label="复制行程" tooltip="复制行程" />
            <ArtifactAction
              icon={DownloadIcon}
              label="下载行程"
              tooltip="下载行程"
            />
          </ArtifactActions>
        </ArtifactHeader>

        <ArtifactContent className="grid min-h-0 grid-rows-[minmax(260px,42vh)_1fr] p-0">
          <div className="relative border-b bg-muted">
            <AmapView
              dayPlans={state.dayPlans}
              activeDay={state.activeDay}
              activePoiId={state.activePoiId}
              onSelectPoi={onSelectPoi}
            />
          </div>

          <div className="min-h-0 overflow-y-auto">
            <section className="mx-auto w-full max-w-3xl px-5 py-5">
              {state.budget?.estimated ? (
                <BudgetSummary state={state} />
              ) : null}

              <DayTabs
                days={state.dayPlans}
                activeDay={state.activeDay}
                onSelectDay={onSelectDay}
              />

              <div className="space-y-8">
                {visibleDays.map((day) => (
                  <DayRoute
                    key={day.day}
                    day={day}
                    activePoiId={state.activePoiId}
                    onSelectPoi={onSelectPoi}
                  />
                ))}
              </div>
            </section>
          </div>
        </ArtifactContent>
      </Artifact>
    </aside>
  );
}

function BudgetSummary({ state }: { state: TripUiState }) {
  const budget = state.budget;
  if (!budget?.estimated) return null;

  return (
    <div className="mb-5 rounded-md border bg-card p-4 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="font-medium text-foreground">
            预计 ¥{Math.round(budget.estimated)}
          </p>
          {budget.limit ? (
            <p className="text-muted-foreground">预算 ¥{budget.limit}</p>
          ) : null}
        </div>
        {budget.over ? <Badge className="border-destructive/30 text-destructive">超预算</Badge> : null}
      </div>
      {budget.note ? (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          {budget.note}
        </p>
      ) : null}
    </div>
  );
}

function DayTabs({
  days,
  activeDay,
  onSelectDay,
}: {
  days: DayPlan[];
  activeDay: number | null;
  onSelectDay: (day: number | null) => void;
}) {
  return (
    <div className="mb-6 flex flex-wrap gap-2">
      <Button
        type="button"
        size="sm"
        variant={activeDay === null ? "default" : "outline"}
        onClick={() => onSelectDay(null)}
      >
        总览
      </Button>
      {days.map((day) => (
        <Button
          key={day.day}
          type="button"
          size="sm"
          variant={activeDay === day.day ? "default" : "outline"}
          onClick={() => onSelectDay(day.day)}
        >
          Day {day.day}
        </Button>
      ))}
    </div>
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
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-xl font-semibold tracking-tight text-foreground">
          Day {day.day}
        </h3>
        {day.weather?.text ? <Badge>{day.weather.text}</Badge> : null}
        {day.weather?.temp ? (
          <span className="text-sm text-muted-foreground">{day.weather.temp}</span>
        ) : null}
      </div>

      <Separator />

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
              "flex w-full items-start gap-3 rounded-md border bg-muted/30 p-3 text-left text-sm transition hover:border-foreground/30",
              activePoiId === day.hotel.poi_id && "border-foreground shadow-sm",
            )}
          >
            <span className="text-muted-foreground">酒店</span>
            <span className="min-w-0">
              <span className="block truncate font-medium text-foreground">
                {day.hotel.name}
              </span>
              {day.hotel.price ? (
                <span className="text-xs text-muted-foreground">
                  ¥{day.hotel.price}/晚
                </span>
              ) : null}
            </span>
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
      <div className="rounded-md border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        {item.from && item.to ? `${item.from} -> ${item.to}` : item.mode ?? "交通"}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onSelectPoi(item.poi_id ?? null)}
      className={cn(
        "flex w-full items-start justify-between gap-3 rounded-md border bg-card p-3 text-left text-sm transition hover:border-foreground/30",
        active && "border-foreground shadow-sm",
      )}
    >
      <span className="min-w-0">
        <span className="block truncate font-medium text-foreground">
          {item.name}
        </span>
        <span className="text-xs text-muted-foreground">
          {item.type === "meal" ? "餐饮" : "景点"}
          {item.cost ? ` · ¥${item.cost}` : ""}
        </span>
      </span>
      {item.indoor ? <Badge>室内</Badge> : null}
    </button>
  );
}
