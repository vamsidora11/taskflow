import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, expect, vi } from 'vitest'
import * as axeMatchers from 'vitest-axe/matchers'
import { tokenStore } from '../api/tokenStore'

expect.extend(axeMatchers)

afterEach(() => {
  cleanup()
  tokenStore.set(null)
  vi.unstubAllGlobals()
})
