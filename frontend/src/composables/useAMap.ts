import { ref, type Ref } from 'vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import type { DayPlan, LngLat } from '../types'

// 按天配色（循环使用）
const DAY_COLORS = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399', '#9B59B6']
const dayColor = (day: number) => DAY_COLORS[(day - 1) % DAY_COLORS.length]

export function useAMap(containerRef: Ref<HTMLElement | null>) {
  const ready = ref(false)
  const error = ref<string | null>(null)

  let AMap: any = null
  let map: any = null
  let infoWindow: any = null
  // poi_id -> { marker, item, day }
  const markerMap = new Map<string, { marker: any; name: string; day: number }>()
  let markerClickCb: ((poiId: string) => void) | null = null
  let routeInstance: any = null

  const init = async (): Promise<void> => {
    const key = import.meta.env.VITE_AMAP_JS_KEY as string | undefined
    if (!key) {
      error.value = '未配置高德地图 Key，请在 frontend/.env 设置 VITE_AMAP_JS_KEY'
      return
    }
    const securityCode = import.meta.env.VITE_AMAP_SECURITY_CODE as string | undefined
    if (securityCode) {
      ;(window as any)._AMapSecurityConfig = { securityJsCode: securityCode }
    }
    try {
      AMap = await AMapLoader.load({
        key,
        version: '2.0',
        plugins: ['AMap.InfoWindow', 'AMap.Driving', 'AMap.Transfer', 'AMap.Walking'],
      })
      if (!containerRef.value) {
        error.value = '地图容器未就绪'
        return
      }
      map = new AMap.Map(containerRef.value, {
        zoom: 11,
        viewMode: '2D',
      })
      infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -30) })
      ready.value = true
    } catch (e: any) {
      error.value = '地图加载失败：' + (e?.message || String(e))
    }
  }

  const clearMarkers = () => {
    if (!map) return
    for (const { marker } of markerMap.values()) map.remove(marker)
    markerMap.clear()
  }

  const renderDayPlans = (plans: DayPlan[], activeDay: number | null): void => {
    if (!map || !AMap) return
    clearMarkers()
    if (infoWindow) infoWindow.close()
    const allMarkers: any[] = []
    for (const dp of plans) {
      const isActive = activeDay === null || dp.day === activeDay
      for (const item of dp.items) {
        const { lng, lat } = item.location
        if (typeof lng !== 'number' || typeof lat !== 'number') continue
        const color = dayColor(dp.day)
        const content =
          `<div class="amap-dot" style="background:${color};opacity:${isActive ? 1 : 0.35};" ` +
          `title="${item.name}"></div>`
        const marker = new AMap.Marker({
          position: [lng, lat],
          content,
          offset: new AMap.Pixel(-7, -7),
          zIndex: isActive ? 120 : 80,
        })
        marker.on('click', () => {
          if (markerClickCb) markerClickCb(item.poi_id)
        })
        map.add(marker)
        markerMap.set(item.poi_id, { marker, name: item.name, day: dp.day })
        allMarkers.push(marker)
      }
    }
    if (allMarkers.length > 0) map.setFitView(allMarkers, false, [60, 60, 60, 60])
  }

  const focusPoi = (poiId: string | null): void => {
    if (!map || !poiId) {
      if (infoWindow) infoWindow.close()
      return
    }
    const hit = markerMap.get(poiId)
    if (!hit) return
    const pos = hit.marker.getPosition()
    map.setCenter(pos)
    if (map.getZoom() < 13) map.setZoom(13)
    infoWindow.setContent(
      `<div style="padding:4px 8px;font-size:13px;font-weight:600;">${hit.name}</div>`,
    )
    infoWindow.open(map, pos)
  }

  const onMarkerClick = (cb: (poiId: string) => void): void => {
    markerClickCb = cb
  }

  const clearRoute = () => {
    if (routeInstance) {
      routeInstance.clear()
      routeInstance = null
    }
  }

  const drawRoute = (start: LngLat, end: LngLat, modeStr: string = '') => {
    if (!map || !AMap) return
    clearRoute()
    
    let PluginClass = AMap.Driving
    let pluginOptions: any = { map: map }

    const execSearch = () => {
      try {
        routeInstance = new PluginClass(pluginOptions)
        routeInstance.search(
          [start.lng, start.lat],
          [end.lng, end.lat],
          (status: string, result: any) => {
            if (status !== 'complete') {
              console.warn('路线规划未完成或失败:', result)
            }
          }
        )
      } catch (e) {
        console.error('绘制路线异常:', e)
      }
    }

    if (modeStr.includes('公交') || modeStr.includes('地铁')) {
      PluginClass = AMap.Transfer
      // 高德公交规划必须指定城市，动态获取当前地图中心所在城市
      map.getCity((info: any) => {
        pluginOptions.city = info.city || info.province || '深圳市'
        execSearch()
      })
    } else {
      if (modeStr.includes('步行')) PluginClass = AMap.Walking
      execSearch()
    }
  }

  const destroy = (): void => {
    clearRoute()
    clearMarkers()
    if (map) { map.destroy(); map = null }
    ready.value = false
  }

  return { ready, error, init, renderDayPlans, focusPoi, onMarkerClick, destroy, drawRoute, clearRoute }
}
