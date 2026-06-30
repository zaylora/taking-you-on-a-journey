import { expect, test } from 'bun:test'
import { normalizeDayPlanTransports } from '../src/utils/dayPlanConnectivity'
import type { DayPlan } from '../src/types'

const loc = (lng: number, lat: number) => ({ lng, lat })

test('adds missing transport between adjacent stops in existing day plans', () => {
  const plans: DayPlan[] = [{
    day: 1,
    center: loc(113.25, 23.12),
    weather: { text: '', temp: '', is_rainy: false, source: '' },
    items: [
      { type: 'attraction', name: '大佛寺', poi_id: 'p1', location: loc(113.2708, 23.1247) },
      { type: 'meal', name: '银记肠粉(北京路店)', poi_id: 'r1', location: loc(113.2705, 23.1239), cost: 80 },
      { type: 'transport', name: '', poi_id: '', location: loc(0, 0), from: '银记肠粉(北京路店)', to: '永庆坊', mode: '市内交通', cost: 15 },
      { type: 'attraction', name: '永庆坊', poi_id: 'p2', location: loc(113.2440, 23.1156) },
    ],
  }]

  const normalized = normalizeDayPlanTransports(plans)

  expect(normalized[0].items.map((item) => [item.type, item.from, item.to])).toEqual([
    ['attraction', undefined, undefined],
    ['transport', '大佛寺', '银记肠粉(北京路店)'],
    ['meal', undefined, undefined],
    ['transport', '银记肠粉(北京路店)', '永庆坊'],
    ['attraction', undefined, undefined],
  ])
})

test('does not duplicate an existing transport between adjacent stops', () => {
  const plans: DayPlan[] = [{
    day: 1,
    center: loc(113.25, 23.12),
    weather: { text: '', temp: '', is_rainy: false, source: '' },
    items: [
      { type: 'attraction', name: '大佛寺', poi_id: 'p1', location: loc(113.2708, 23.1247) },
      { type: 'transport', name: '', poi_id: '', location: loc(0, 0), from: '大佛寺', to: '银记肠粉(北京路店)', mode: '市内交通', cost: 15 },
      { type: 'meal', name: '银记肠粉(北京路店)', poi_id: 'r1', location: loc(113.2705, 23.1239), cost: 80 },
    ],
  }]

  const normalized = normalizeDayPlanTransports(plans)

  expect(normalized[0].items.filter((item) => item.type === 'transport')).toHaveLength(1)
})
