// @vitest-environment node
// ESLint의 렌더링 안전·저장소 금지 규칙이 앱 소스에서 실제로 걸리는지 확인한다.
import { ESLint } from 'eslint'
import { describe, expect, it } from 'vitest'

const eslint = new ESLint()

async function ruleIds(code: string): Promise<string[]> {
  const [res] = await eslint.lintText(code, { filePath: 'src/components/__lint_probe__.tsx' })
  return res.messages.map((m) => m.ruleId ?? 'fatal')
}

describe('ESLint 안전 규칙', () => {
  it.each([
    ['JSX dangerouslySetInnerHTML', 'export const A = (p: { h: string }) => <div dangerouslySetInnerHTML={{ __html: p.h }} />'],
    ['iframe srcDoc', 'export const A = (p: { h: string }) => <iframe srcDoc={p.h} />'],
    ['innerHTML 대입', 'export function f(el: HTMLElement, h: string) { el.innerHTML = h }'],
    ['outerHTML 대입', 'export function f(el: HTMLElement, h: string) { el.outerHTML = h }'],
    ['대괄호 innerHTML', "export function f(el: HTMLElement, h: string) { el['innerHTML'] = h }"],
    ['insertAdjacentHTML', "export function f(el: HTMLElement, h: string) { el.insertAdjacentHTML('beforeend', h) }"],
    ['createContextualFragment', 'export function f(h: string) { return document.createRange().createContextualFragment(h) }'],
    ['document.write', 'export function f(h: string) { document.write(h) }'],
    ['localStorage', "export function f(t: string) { localStorage.setItem('t', t) }"],
    ['window.sessionStorage', "export function f(t: string) { window.sessionStorage.setItem('t', t) }"],
    ['document.cookie', 'export function f() { return document.cookie }'],
  ])('%s → 오류', async (_name, code) => {
    const ids = await ruleIds(code)
    expect(ids.some((id) => id === 'no-restricted-syntax' || id === 'no-restricted-properties')).toBe(true)
  })

  it('eval → 오류', async () => {
    expect(await ruleIds('export function f(s: string) { return eval(s) }')).toContain('no-eval')
  })

  it('일반 텍스트 렌더링은 통과', async () => {
    expect(await ruleIds('export const A = (p: { t: string }) => <p>{p.t}</p>')).toEqual([])
  })
})
