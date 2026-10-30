import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './api/errors'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Client errors (4xx) will not succeed on retry; transient failures get one more try.
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 1,
        refetchOnWindowFocus: false,
      },
    },
  })
}
