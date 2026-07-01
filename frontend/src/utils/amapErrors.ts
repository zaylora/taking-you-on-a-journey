export function isAmapQuotaLimit(result: unknown): boolean {
  const text = typeof result === 'string' ? result : JSON.stringify(result ?? '')
  return text.includes('CUQPS_HAS_EXCEEDED_THE_LIMIT')
}
