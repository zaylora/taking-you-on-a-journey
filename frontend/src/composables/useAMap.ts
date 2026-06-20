import { ref, type Ref } from 'vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import type { DayPlan, LngLat, TripItem, Hotel } from '../types'

// 按天配色（循环使用）
const DAY_COLORS = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399', '#9B59B6']
const dayColor = (day: number) => DAY_COLORS[(day - 1) % DAY_COLORS.length]

export function useAMap(containerRef: Ref<HTMLElement | null>) {
  const ready = ref(false)
  const error = ref<string | null>(null)

  let AMap: any = null
  let map: any = null
  let infoWindow: any = null
  // poi_id -> { marker, name, item, hotel, day }
  const markerMap = new Map<string, { marker: any; name: string; item?: TripItem; hotel?: Hotel; day: number }>()
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
        plugins: ['AMap.InfoWindow', 'AMap.Driving', 'AMap.Transfer', 'AMap.Walking', 'AMap.PlaceSearch'],
      })
      if (!containerRef.value) {
        error.value = '地图容器未就绪'
        return
      }
      map = new AMap.Map(containerRef.value, {
        zoom: 11,
        viewMode: '2D',
      })
      infoWindow = new AMap.InfoWindow({ 
        offset: new AMap.Pixel(0, -30),
        autoMove: false 
      })
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
    let globalPointIndex = 1
    
    for (const dp of plans) {
      const isActive = activeDay === null || dp.day === activeDay
      let dayPointIndex = 1
      
      for (const item of dp.items) {
        if (item.type === 'transport') continue
        const { lng, lat } = item.location
        if (typeof lng !== 'number' || typeof lat !== 'number') continue
        const color = dayColor(dp.day)
        
        const pointIndex = activeDay === null ? globalPointIndex : dayPointIndex
        const content = isActive
          ? `<div style="background:${color};opacity:1;color:#fff;border-radius:50%;width:24px;height:24px;line-height:24px;text-align:center;font-size:12px;font-weight:bold;box-shadow:0 2px 4px rgba(0,0,0,0.2);" title="${item.name}">${pointIndex}</div>`
          : `<div class="amap-dot" style="background:${color};opacity:0.35;" title="${item.name}"></div>`
          
        const marker = new AMap.Marker({
          position: [lng, lat],
          content,
          offset: isActive ? new AMap.Pixel(-12, -12) : new AMap.Pixel(-7, -7),
          zIndex: isActive ? 120 : 80,
        })
        marker.on('click', () => {
          if (markerClickCb) markerClickCb(item.poi_id)
        })
        map.add(marker)
        markerMap.set(item.poi_id, { marker, name: item.name, item, day: dp.day })
        if (isActive) allMarkers.push(marker)
        globalPointIndex++
        dayPointIndex++
      }
      
      if (dp.hotel) {
        const { lng, lat } = dp.hotel.location
        if (typeof lng === 'number' && typeof lat === 'number') {
          const color = dayColor(dp.day)
          
          const pointIndex = activeDay === null ? globalPointIndex : dayPointIndex
          const content = isActive
            ? `<div style="background:${color};opacity:1;color:#fff;border-radius:4px;width:24px;height:24px;line-height:24px;text-align:center;font-size:12px;font-weight:bold;box-shadow:0 2px 4px rgba(0,0,0,0.2);" title="${dp.hotel.name}">${pointIndex}</div>`
            : `<div class="amap-dot" style="background:${color};opacity:0.35;border-radius:2px;width:12px;height:12px;" title="${dp.hotel.name}"></div>`
            
          const marker = new AMap.Marker({
            position: [lng, lat],
            content,
            offset: isActive ? new AMap.Pixel(-12, -12) : new AMap.Pixel(-6, -6),
            zIndex: isActive ? 130 : 80,
          })
          marker.on('click', () => {
            if (markerClickCb) markerClickCb(dp.hotel!.poi_id)
          })
          map.add(marker)
          markerMap.set(dp.hotel.poi_id, { marker, name: dp.hotel.name, hotel: dp.hotel, day: dp.day })
          if (isActive) allMarkers.push(marker)
          globalPointIndex++
          dayPointIndex++
        }
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
    
    const targetZoom = Math.max(map.getZoom(), 14)
    map.setZoomAndCenter(targetZoom, pos)
    // 向下偏移120像素，使得弹出的 InfoWindow 正好在视口中间
    map.panBy(0, -120)

    let html = `<div style="padding:4px 8px;font-size:13px;width:240px;line-height:1.5;">`
    html += `<!-- img-placeholder -->`
    html += `<div style="font-weight:600;font-size:14px;margin-bottom:4px;">${hit.name}</div>`
    
    if (hit.item) {
      if (hit.item.cost) html += `<div style="color:#e6a23c;font-size:12px;margin-bottom:4px;">预计花费: ¥${hit.item.cost}</div>`
      if (hit.item.note) html += `<div style="color:#606266;font-size:12px;white-space:pre-wrap;">${hit.item.note}</div>`
    } else if (hit.hotel) {
      if (hit.hotel.level) html += `<div style="color:#409eff;font-size:12px;margin-bottom:4px;">${hit.hotel.level}</div>`
      if (hit.hotel.price) html += `<div style="color:#e6a23c;font-size:12px;margin-bottom:4px;">参考价: ¥${hit.hotel.price}/晚</div>`
    }

    html += `</div>`
    infoWindow.setContent(html)
    infoWindow.open(map, pos)

    // 异步拉取高德地点详情获取图片
    const placeSearch = new AMap.PlaceSearch({ extensions: 'all' })
    placeSearch.getDetails(poiId, (status: string, result: any) => {
      if (status === 'complete' && result.info === 'OK') {
        const poi = result.poiList.pois[0]
        if (poi && poi.photos && poi.photos.length > 0) {
          const imgUrl = poi.photos[0].url
          const imgHtml = `<img src="${imgUrl}" style="width:100%; height:120px; object-fit:cover; border-radius:6px; margin-bottom:8px; display:block;" />`
          const newHtml = html.replace('<!-- img-placeholder -->', imgHtml)
          infoWindow.setContent(newHtml)
        }
      }
    })
  }

  const onMarkerClick = (cb: (poiId: string) => void): void => {
    markerClickCb = cb
  }

  // 选中态下只显示相关点：poiIds=null 时恢复全部显示（总览/按天），
  // 否则只显示给定 poi_id 的标记（单点=1个，单段路线=起讫2个），其余隐藏。
  const setVisibleMarkers = (poiIds: string[] | null): void => {
    if (!map) return
    for (const [poiId, { marker }] of markerMap.entries()) {
      if (poiIds === null || poiIds.includes(poiId)) marker.show()
      else marker.hide()
    }
  }

  let overviewRouteInstances: any[] = []
  // 总览路线绘制代次：每次清除/重绘 +1。在途的异步 search 回调返回时若发现代次已变，
  // 说明本次绘制已被取代，需把自己刚渲染的路线清掉——否则会留下清不掉的孤儿路线。
  let overviewGeneration = 0

  const clearOverviewRoute = () => {
    overviewGeneration++
    for (const instance of overviewRouteInstances) {
      if (instance && instance.clear) instance.clear()
    }
    overviewRouteInstances = []
  }

  // 总览路线按段绘制：每段交通用自己的 mode 规划（步行/公交/驾车），
  // 而非把全天点位串成一条驾车路线。legs 由调用方（MapView）依交通段算好起讫与 mode。
  const drawOverviewRoute = (legs: Array<{ start: LngLat; end: LngLat; mode?: string }>) => {
    if (!map || !AMap) return
    clearOverviewRoute()
    const myGen = overviewGeneration

    for (const leg of legs) {
      const { start, end } = leg
      const mode = leg.mode || ''
      if (!start || !end || typeof start.lng !== 'number' || typeof end.lng !== 'number') continue

      let PluginClass = AMap.Driving
      const pluginOptions: any = { map, hideMarkers: true, showTraffic: false, autoFitView: false }

      const execSearch = () => {
        // 公交城市异步返回时，本次总览可能已被新的清除/重绘取代
        if (myGen !== overviewGeneration) return
        try {
          const instance = new PluginClass(pluginOptions)
          overviewRouteInstances.push(instance)
          instance.search(
            [start.lng, start.lat],
            [end.lng, end.lat],
            (status: string, result: any) => {
              // 迟到的孤儿回调：本次绘制已被新的清除/重绘取代，抹掉它刚渲染的路线后退出
              if (myGen !== overviewGeneration) {
                instance.clear()
                return
              }
              if (status !== 'complete') {
                console.warn('总览分段路线规划异常:', result)
              }
            }
          )
        } catch (e) {
          console.error('总览分段路线绘制异常:', e)
        }
      }

      if (mode.includes('公交') || mode.includes('地铁')) {
        PluginClass = AMap.Transfer
        // 高德公交规划必须指定城市，动态获取当前地图中心所在城市
        map.getCity((info: any) => {
          pluginOptions.city = info.city || info.province || '深圳市'
          execSearch()
        })
      } else {
        if (mode.includes('步行')) PluginClass = AMap.Walking
        execSearch()
      }
    }
  }

  const clearRoute = () => {
    if (routeInstance) {
      routeInstance.clear()
      routeInstance = null
    }
  }

  const drawRoute = (start: LngLat, end: LngLat, modeStr: string = '', onComplete?: (info: {distance: number, time: number}) => void) => {
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
            } else if (onComplete) {
              const plan = result.plans ? result.plans[0] : (result.routes ? result.routes[0] : null)
              if (plan) {
                onComplete({ distance: plan.distance, time: plan.time })
              }
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

  const fetchRouteInfo = (start: LngLat, end: LngLat, modeStr: string = ''): Promise<{distance: number, time: number} | null> => {
    return new Promise((resolve) => {
      if (!AMap) return resolve(null)
      
      let PluginClass = AMap.Driving
      let pluginOptions: any = {}

      const execSearch = () => {
        try {
          const instance = new PluginClass(pluginOptions)
          instance.search(
            [start.lng, start.lat],
            [end.lng, end.lat],
            (status: string, result: any) => {
              if (status === 'complete') {
                const plan = result.plans ? result.plans[0] : (result.routes ? result.routes[0] : null)
                if (plan) {
                  resolve({ distance: plan.distance, time: plan.time })
                  return
                }
              }
              resolve(null)
            }
          )
        } catch (e) {
          console.error('获取路线数据异常:', e)
          resolve(null)
        }
      }

      if (modeStr.includes('公交') || modeStr.includes('地铁')) {
        PluginClass = AMap.Transfer
        map.getCity((info: any) => {
          pluginOptions.city = info.city || info.province || '深圳市'
          execSearch()
        })
      } else {
        if (modeStr.includes('步行')) PluginClass = AMap.Walking
        execSearch()
      }
    })
  }

  const destroy = (): void => {
    clearRoute()
    clearMarkers()
    if (map) { map.destroy(); map = null }
    ready.value = false
  }

  return { ready, error, init, renderDayPlans, focusPoi, onMarkerClick, setVisibleMarkers, destroy, drawRoute, clearRoute, fetchRouteInfo, drawOverviewRoute, clearOverviewRoute }
}
