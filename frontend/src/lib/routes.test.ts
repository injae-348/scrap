import { describe, expect, it } from 'vitest'
import { isEditPath, keepsScreenOnExpiry } from './routes'

describe('routes', () => {
  it('편집 경로', () => {
    for (const p of ['/scraps/new', '/liked/scraps/new', '/scraps/12/edit', '/search/scraps/3/edit']) expect(isEditPath(p)).toBe(true)
    for (const p of ['/', '/scraps/12', '/settings', '/settings/totp']) expect(isEditPath(p)).toBe(false)
  })
  it('만료돼도 남기는 화면: 편집 + 2차 인증 재설정', () => {
    expect(keepsScreenOnExpiry('/scraps/new')).toBe(true)
    expect(keepsScreenOnExpiry('/settings/totp')).toBe(true)
    expect(keepsScreenOnExpiry('/settings')).toBe(false)
    expect(keepsScreenOnExpiry('/scraps/12')).toBe(false)
  })
})
