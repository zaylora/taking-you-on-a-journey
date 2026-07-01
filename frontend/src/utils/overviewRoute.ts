import type { DayPlan, LngLat } from '../types'

export interface OverviewLeg {
  start: LngLat
  end: LngLat
  mode?: string
}

const validLoc = (loc: unknown): loc is LngLat => {
  if (!loc || typeof loc !== 'object') return false
  const maybeLoc = loc as Partial<LngLat>
  return (
    typeof maybeLoc.lng === 'number'
    && typeof maybeLoc.lat === 'number'
    && (maybeLoc.lng !== 0 || maybeLoc.lat !== 0)
  )
}

export function buildOverviewLegs(plans: DayPlan[], connectDays = false): OverviewLeg[] {
  const legs: OverviewLeg[] = []
  let previousDayTail: { loc: LngLat; mode: string } | null = null

  for (const dp of plans) {
    const stops: Array<{ loc: LngLat; mode: string }> = []
    let pendingMode = ''
    for (const item of dp.items) {
      if (item.type === 'transport') {
        if (item.mode) pendingMode = item.mode
        continue
      }
      if (validLoc(item.location)) {
        stops.push({ loc: item.location, mode: pendingMode })
        pendingMode = ''
      }
    }
    if (dp.hotel && validLoc(dp.hotel.location)) {
      stops.push({ loc: dp.hotel.location, mode: pendingMode })
    }
    if (connectDays && previousDayTail && stops.length > 0) {
      legs.push({ start: previousDayTail.loc, end: stops[0].loc, mode: stops[0].mode })
    }
    for (let i = 0; i + 1 < stops.length; i++) {
      legs.push({ start: stops[i].loc, end: stops[i + 1].loc, mode: stops[i + 1].mode })
    }
    previousDayTail = stops.at(-1) ?? previousDayTail
  }
  return legs
}
