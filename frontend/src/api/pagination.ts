import type { Page } from './types'

/** Follows next_cursor until the list is exhausted. */
export async function fetchAll<T>(
  fetchPage: (cursor: string | null) => Promise<Page<T>>,
): Promise<T[]> {
  const items: T[] = []
  let cursor: string | null = null
  do {
    const page: Page<T> = await fetchPage(cursor)
    items.push(...page.items)
    cursor = page.next_cursor ?? null
  } while (cursor)
  return items
}
