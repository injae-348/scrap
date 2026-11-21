import { describe, expect, it } from 'vitest'
import { displayText } from './text'

describe('displayText', () => {
  it.each([
    ['U+202A~202E', 'a‪b‫c‬d‭e‮f', 'abcdef'],
    ['U+2066~2069', 'a⁦b⁧c⁨d⁩e', 'abcde'],
    ['U+200E/200F', 'a‎b‏c', 'abc'],
    ['U+061C', 'a؜b', 'ab'],
  ])('글자 방향 서식 문자(%s)를 지운다', (_n, input, out) => {
    expect(displayText(input)).toBe(out)
  })
  it('일반 한글·영문·이모지는 그대로', () => {
    expect(displayText('가상 제목 ABC 🙂')).toBe('가상 제목 ABC 🙂')
  })
})
