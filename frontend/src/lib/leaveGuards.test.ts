import { describe, expect, it, vi } from 'vitest'
import { bypassAllLeaveGuards, hasActiveLeaveGuard, registerLeaveGuard } from './leaveGuards'

describe('leaveGuards', () => {
  it('등록·해제와 일괄 해제', () => {
    expect(hasActiveLeaveGuard()).toBe(false)
    const bypass = vi.fn()
    const off = registerLeaveGuard({ bypass })
    expect(hasActiveLeaveGuard()).toBe(true)
    bypassAllLeaveGuards()
    expect(bypass).toHaveBeenCalledTimes(1)
    off()
    expect(hasActiveLeaveGuard()).toBe(false)
  })
})
