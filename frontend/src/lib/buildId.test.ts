import { describe, expect, it } from 'vitest'
import { BUILD_ID_ENV, BUILD_ID_META, currentBuildId, resolveBuildId, shortBuildId } from './buildId'

describe('빌드 식별자', () => {
  it('환경변수 이름과 meta 이름', () => {
    expect(BUILD_ID_ENV).toBe('VITE_APP_BUILD_ID')
    expect(BUILD_ID_META).toBe('app-build')
  })

  it('환경변수 값(커밋 SHA 등)을 그대로 쓴다 (앞뒤 공백 제거)', () => {
    const sha = '0123456789abcdef0123456789abcdef01234567'
    expect(resolveBuildId(sha)).toBe(sha)
    expect(resolveBuildId(`  ${sha}\n`)).toBe(sha)
    expect(resolveBuildId('v1.2.3_rc-1')).toBe('v1.2.3_rc-1')
  })

  it('값이 없거나 비면 빌드 시각으로 대신한다 (빌드마다 달라짐)', () => {
    const t = new Date('2026-11-21T10:30:05.123Z')
    expect(resolveBuildId(undefined, t)).toBe('local-20261121T103005Z')
    expect(resolveBuildId('', t)).toBe('local-20261121T103005Z')
    expect(resolveBuildId('   ', t)).toBe('local-20261121T103005Z')
    expect(resolveBuildId(undefined, new Date('2026-11-21T10:30:06Z'))).not.toBe(resolveBuildId(undefined, t))
  })

  it.each(['a"b', '<x>', 'a b', 'a/b', 'x'.repeat(65), '한글'])('형식이 맞지 않는 값 %s → 빌드 중단', (v) => {
    expect(() => resolveBuildId(v)).toThrow(BUILD_ID_ENV)
  })

  it('화면 표시: 커밋 SHA는 앞 7자, 그 밖은 그대로', () => {
    expect(shortBuildId('0123456789abcdef0123456789abcdef01234567')).toBe('0123456')
    expect(shortBuildId('local-20261121T103005Z')).toBe('local-20261121T103005Z')
  })

  it('페이지의 meta에서 읽는다', () => {
    const meta = document.createElement('meta')
    meta.name = 'app-build'
    meta.content = 'abc1234'
    document.head.appendChild(meta)
    try {
      expect(currentBuildId(document)).toBe('abc1234')
    } finally {
      meta.remove()
    }
    expect(currentBuildId(document)).toBeNull()
  })
})
