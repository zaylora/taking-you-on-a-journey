import type { DayPlan, TripItem } from '../types'

export function normalizeDayPlanTransports(plans: DayPlan[]): DayPlan[] {
  return plans.map((day) => ({
    ...day,
    items: normalizeDayItems(day.items || []),
  }))
}

const isStop = (item: TripItem) => item.type !== 'transport' && Boolean(item.name)

const isTransportBetween = (item: TripItem | undefined, from: TripItem, to: TripItem) =>
  item?.type === 'transport' && item.from === from.name && item.to === to.name

const makeTransport = (from: TripItem, to: TripItem): TripItem => ({
  type: 'transport',
  name: '',
  poi_id: '',
  location: { lng: 0, lat: 0 },
  mode: '市内交通',
  from: from.name,
  to: to.name,
  cost: 15,
})

function normalizeDayItems(items: TripItem[]): TripItem[] {
  const normalized: TripItem[] = []
  let previousStop: TripItem | null = null

  for (const item of items) {
    if (isStop(item)) {
      if (previousStop && !isTransportBetween(normalized.at(-1), previousStop, item)) {
        normalized.push(makeTransport(previousStop, item))
      }
      normalized.push(item)
      previousStop = item
    } else {
      normalized.push(item)
    }
  }

  return normalized
}
