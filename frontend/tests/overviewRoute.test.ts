import { expect, test } from 'bun:test'
import { buildOverviewLegs } from '../src/utils/overviewRoute'
import type { DayPlan } from '../src/types'

const loc = (lng: number, lat: number) => ({ lng, lat })

const plans: DayPlan[] = [
  {
    day: 1,
    center: loc(113.25, 23.12),
    weather: { text: '', temp: '', is_rainy: false, source: '' },
    items: [
      { type: 'attraction', name: '大佛寺', poi_id: 'p1', location: loc(113.2708, 23.1247) },
      { type: 'transport', name: '', poi_id: '', location: loc(0, 0), from: '大佛寺', to: '永庆坊', mode: '市内交通' },
      { type: 'attraction', name: '永庆坊', poi_id: 'p2', location: loc(113.2440, 23.1156) },
    ],
  },
  {
    day: 2,
    center: loc(113.31, 23.10),
    weather: { text: '', temp: '', is_rainy: false, source: '' },
    items: [
      { type: 'attraction', name: '广州塔', poi_id: 'p3', location: loc(113.3246, 23.1066) },
      { type: 'transport', name: '', poi_id: '', location: loc(0, 0), from: '广州塔', to: '花城广场', mode: '市内交通' },
      { type: 'attraction', name: '花城广场', poi_id: 'p4', location: loc(113.3235, 23.1194) },
    ],
  },
]

test('connects the last stop of one day to the first stop of the next day in overview mode', () => {
  const legs = buildOverviewLegs(plans, true)

  expect(legs.map((leg) => [leg.start, leg.end])).toEqual([
    [loc(113.2708, 23.1247), loc(113.2440, 23.1156)],
    [loc(113.2440, 23.1156), loc(113.3246, 23.1066)],
    [loc(113.3246, 23.1066), loc(113.3235, 23.1194)],
  ])
})

test('keeps a single day route scoped to that day', () => {
  const legs = buildOverviewLegs(plans.slice(0, 1), false)

  expect(legs.map((leg) => [leg.start, leg.end])).toEqual([
    [loc(113.2708, 23.1247), loc(113.2440, 23.1156)],
  ])
})
