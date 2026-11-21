import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/http'
import { useRetryCountdown } from './useRetryCountdown'

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-21T00:00:00Z'))
})
afterEach(() => vi.useRealTimers())

describe('useRetryCountdown', () => {
  it('429가 아니면 0', () => {
    const { result } = renderHook(() => useRetryCountdown(new ApiError(400, 'invalid_input', 'x')))
    expect(result.current).toBe(0)
  })

  it('Retry-After부터 줄어든다', () => {
    const err = new ApiError(429, 'too_many_attempts', 'x', 120)
    const { result } = renderHook(() => useRetryCountdown(err))
    expect(result.current).toBe(120)
    act(() => vi.advanceTimersByTime(30_000))
    expect(result.current).toBe(90)
  })

  it('타이머가 멈춰 있던 동안의 시간도 화면 복귀 때 반영한다 (절대 시각 기준)', () => {
    const err = new ApiError(429, 'too_many_attempts', 'x', 120)
    const { result } = renderHook(() => useRetryCountdown(err))
    // 타이머 없이 시계만 100초 흐름 (백그라운드에서 타이머가 멈춘 경우)
    vi.setSystemTime(Date.now() + 100_000)
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(result.current).toBe(20)
    vi.setSystemTime(Date.now() + 60_000)
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(result.current).toBe(0)
  })
})
