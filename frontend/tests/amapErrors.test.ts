import { expect, test } from 'bun:test'
import { isAmapQuotaLimit } from '../src/utils/amapErrors'

test('recognizes AMap QPS quota errors', () => {
  expect(isAmapQuotaLimit({ info: 'CUQPS_HAS_EXCEEDED_THE_LIMIT' })).toBe(true)
  expect(isAmapQuotaLimit({ message: 'AMap says CUQPS_HAS_EXCEEDED_THE_LIMIT' })).toBe(true)
  expect(isAmapQuotaLimit({ info: 'INVALID_USER_KEY' })).toBe(false)
})
