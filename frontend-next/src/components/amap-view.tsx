"use client";

import { MapPinned, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { DayPlan, LngLat } from "@/lib/types";

const dayColors = ["#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed"];

interface AmapPixelConstructor {
  new (x: number, y: number): unknown;
}

interface AmapMarker {
  on(event: string, handler: () => void): void;
  getPosition(): unknown;
}

interface AmapMarkerConstructor {
  new (options: {
    position: [number, number];
    content: string;
    offset: unknown;
    zIndex: number;
  }): AmapMarker;
}

interface AmapMap {
  add(target: AmapMarker): void;
  remove(target: AmapMarker): void;
  setFitView(
    markers: AmapMarker[],
    immediately?: boolean,
    padding?: number[],
  ): void;
  getZoom(): number;
  setZoomAndCenter(zoom: number, position: unknown): void;
  destroy(): void;
}

interface AmapMapConstructor {
  new (
    container: HTMLElement,
    options: { zoom: number; viewMode: string },
  ): AmapMap;
}

interface AmapNamespace {
  Map: AmapMapConstructor;
  Marker: AmapMarkerConstructor;
  Pixel: AmapPixelConstructor;
}

interface AmapViewProps {
  dayPlans: DayPlan[];
  activeDay: number | null;
  activePoiId: string | null;
  onSelectPoi: (poiId: string | null) => void;
}

export function AmapView({
  dayPlans,
  activeDay,
  activePoiId,
  onSelectPoi,
}: AmapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<AmapMap | null>(null);
  const amapRef = useRef<AmapNamespace | null>(null);
  const markerMapRef = useRef<Map<string, AmapMarker>>(new Map());
  const [loadError, setLoadError] = useState<string | null>(null);
  const key = process.env.NEXT_PUBLIC_AMAP_JS_KEY;
  const securityCode = process.env.NEXT_PUBLIC_AMAP_SECURITY_CODE;
  const error = key ? loadError : "未配置高德地图 Key";

  const mapSignature = useMemo(
    () =>
      dayPlans
        .flatMap((day) => [
          `day:${day.day}`,
          ...day.items.map(
            (item) =>
              `${item.poi_id ?? item.name}@${item.location?.lng ?? ""},${
                item.location?.lat ?? ""
              }`,
          ),
          day.hotel
            ? `hotel:${day.hotel.poi_id}@${day.hotel.location.lng},${day.hotel.location.lat}`
            : "",
        ])
        .join("|"),
    [dayPlans],
  );

  useEffect(() => {
    if (!key) {
      return;
    }
    if (!containerRef.current || mapRef.current) return;
    let cancelled = false;
    const markerMap = markerMapRef.current;

    if (securityCode) {
      (
        window as Window & {
          _AMapSecurityConfig?: { securityJsCode: string };
        }
      )._AMapSecurityConfig = { securityJsCode: securityCode };
    }

    import("@amap/amap-jsapi-loader")
      .then(({ default: AMapLoader }) =>
        AMapLoader.load({
          key,
          version: "2.0",
          plugins: ["AMap.InfoWindow", "AMap.Polyline"],
        }),
      )
      .then((AMap) => {
        if (cancelled || !containerRef.current) return;
        amapRef.current = AMap as AmapNamespace;
        mapRef.current = new AMap.Map(containerRef.current, {
          zoom: 11,
          viewMode: "2D",
        });
        setLoadError(null);
      })
      .catch((err) => {
        setLoadError(`地图加载失败：${err?.message ?? String(err)}`);
      });

    return () => {
      cancelled = true;
      mapRef.current?.destroy?.();
      mapRef.current = null;
      markerMap.clear();
    };
  }, [key, securityCode]);

  useEffect(() => {
    renderMarkers({
      AMap: amapRef.current,
      map: mapRef.current,
      markerMap: markerMapRef.current,
      dayPlans,
      activeDay,
      onSelectPoi,
    });
  }, [activeDay, dayPlans, mapSignature, onSelectPoi]);

  useEffect(() => {
    if (!activePoiId || !mapRef.current) return;
    const marker = markerMapRef.current.get(activePoiId);
    const position = marker?.getPosition?.();
    if (position) {
      mapRef.current.setZoomAndCenter(
        Math.max(mapRef.current.getZoom(), 14),
        position,
      );
    }
  }, [activePoiId]);

  return (
    <div className="relative h-full min-h-[260px] w-full">
      <div ref={containerRef} className="h-full min-h-[260px] w-full" />
      {error ? <MapOverlay title={error} /> : null}
      {!error && !dayPlans.length ? (
        <MapOverlay title="生成行程后显示地图" />
      ) : null}
    </div>
  );
}

function MapOverlay({ title }: { title: string }) {
  const Icon =
    title.includes("失败") || title.includes("未配置")
      ? TriangleAlert
      : MapPinned;
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-muted p-6 text-center">
      <div>
        <Icon className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          配置 NEXT_PUBLIC_AMAP_JS_KEY 后加载真实地图
        </p>
      </div>
    </div>
  );
}

function renderMarkers({
  AMap,
  map,
  markerMap,
  dayPlans,
  activeDay,
  onSelectPoi,
}: {
  AMap: AmapNamespace | null;
  map: AmapMap | null;
  markerMap: Map<string, AmapMarker>;
  dayPlans: DayPlan[];
  activeDay: number | null;
  onSelectPoi: (poiId: string | null) => void;
}) {
  if (!AMap || !map) return;
  for (const marker of markerMap.values()) {
    map.remove(marker);
  }
  markerMap.clear();

  const markers: AmapMarker[] = [];
  for (const day of dayPlans) {
    const active = activeDay === null || activeDay === day.day;
    const color = dayColors[(day.day - 1) % dayColors.length];
    let index = 1;

    for (const item of day.items) {
      if (
        item.type === "transport" ||
        !item.poi_id ||
        !isLocation(item.location)
      ) {
        continue;
      }
      const marker = new AMap.Marker({
        position: [item.location.lng, item.location.lat],
        content: markerHtml(index, color, active),
        offset: new AMap.Pixel(-12, -12),
        zIndex: active ? 120 : 80,
      });
      marker.on("click", () => onSelectPoi(item.poi_id ?? null));
      map.add(marker);
      markerMap.set(item.poi_id, marker);
      if (active) markers.push(marker);
      index += 1;
    }

    if (day.hotel && isLocation(day.hotel.location)) {
      const marker = new AMap.Marker({
        position: [day.hotel.location.lng, day.hotel.location.lat],
        content: markerHtml(index, color, active, true),
        offset: new AMap.Pixel(-12, -12),
        zIndex: active ? 130 : 80,
      });
      marker.on("click", () => onSelectPoi(day.hotel?.poi_id ?? null));
      map.add(marker);
      markerMap.set(day.hotel.poi_id, marker);
      if (active) markers.push(marker);
    }
  }

  if (markers.length) map.setFitView(markers, false, [50, 50, 50, 50]);
}

function markerHtml(
  index: number,
  color: string,
  active: boolean,
  hotel = false,
) {
  const radius = hotel ? "5px" : "50%";
  const opacity = active ? 1 : 0.38;
  return `<div style="width:24px;height:24px;line-height:24px;text-align:center;border-radius:${radius};background:${color};opacity:${opacity};color:#fff;font-size:12px;font-weight:700;box-shadow:0 2px 8px rgba(0,0,0,.22);">${index}</div>`;
}

function isLocation(value: unknown): value is LngLat {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as LngLat).lng === "number" &&
    typeof (value as LngLat).lat === "number"
  );
}
