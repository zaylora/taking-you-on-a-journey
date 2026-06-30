export async function runSequentially<T>(
  items: T[],
  task: (item: T) => Promise<void>,
  options: { shouldContinue?: () => boolean; delayMs?: number } = {},
): Promise<void> {
  for (const item of items) {
    if (options.shouldContinue && !options.shouldContinue()) return
    await task(item)
    if (options.delayMs && options.delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, options.delayMs))
    }
  }
}

let queue = Promise.resolve()

export function enqueueRouteTask<T>(task: () => Promise<T>): Promise<T> {
  const next = queue.then(task, task)
  queue = next.then(() => undefined, () => undefined)
  return next
}
