import { expect, test } from 'bun:test'
import { runSequentially } from '../src/utils/routeScheduler'

test('runs route searches one at a time', async () => {
  let inFlight = 0
  let maxInFlight = 0
  const order: string[] = []

  await runSequentially(['a', 'b', 'c'], async (item) => {
    inFlight += 1
    maxInFlight = Math.max(maxInFlight, inFlight)
    order.push(`start:${item}`)
    await Promise.resolve()
    order.push(`end:${item}`)
    inFlight -= 1
  })

  expect(maxInFlight).toBe(1)
  expect(order).toEqual(['start:a', 'end:a', 'start:b', 'end:b', 'start:c', 'end:c'])
})

test('stops before the next route search when the generation is stale', async () => {
  const visited: string[] = []
  let active = true

  await runSequentially(
    ['a', 'b', 'c'],
    async (item) => {
      visited.push(item)
      active = false
    },
    { shouldContinue: () => active },
  )

  expect(visited).toEqual(['a'])
})
