// VITE_ 환경변수 허용 목록 검사.
// VITE_ 로 시작하는 값은 빌드 결과물(브라우저 번들, 공개 이미지)에 그대로 들어가므로 공개 값만 쓴다.
// 새 VITE_ 변수를 쓰려면 아래 ALLOWED 에 이름과 "공개해도 되는 이유"를 적는다 (리뷰에서 확인).
import ts from 'typescript'
import { describe, expect, it } from 'vitest'
import { BUILD_ID_ENV } from './lib/buildId'

/** 쓸 수 있는 VITE_ 변수와 공개해도 되는 이유 */
const ALLOWED: Record<string, string> = {
  // 빌드 식별자(커밋 SHA 또는 빌드 시각). 공개 저장소의 커밋 SHA라 숨길 값이 아니다. vite.config.ts 가 index.html meta로만 넣는다.
  VITE_APP_BUILD_ID: '빌드 식별자 (커밋 SHA 등 공개 값)',
}
/**
 * vite.config.ts 가 process.env 에서 읽어도 되는 이름. 빌드 설정에서만 쓰고 번들에는 넣지 않는다.
 * (VITE_ 허용 목록은 vite.config.ts 에서도 읽을 수 있다. 빌드 식별자는 index.html meta로만 나간다)
 */
const CONFIG_ONLY: Record<string, string> = {
  VITEST: '테스트 실행 여부 (vitest가 설정, PWA 플러그인을 끄는 데만 씀)',
}
/** vite.config.ts 에서 process.env[상수] 로 읽을 때 상수 이름 → 실제 환경변수 이름 */
const CONFIG_ENV_CONSTANTS: Record<string, string> = { BUILD_ID_ENV }
/** Vite가 기본으로 주는 값 (비밀값이 아님) */
const BUILTIN = new Set(['MODE', 'DEV', 'PROD', 'SSR', 'BASE_URL'])
/** import.meta 의 다른 속성 중 환경변수를 읽지 않는 것 */
const META_OK = new Set(['glob', 'hot', 'url'])

const sources = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>
const viteConfig = Object.values(
  import.meta.glob('../vite.config.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
)[0]
const indexHtml = Object.values(
  import.meta.glob('../index.html', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
)[0]

function parse(code: string, file: string) {
  return ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
}

function withoutComments(code: string, file: string): string {
  return ts.createPrinter({ removeComments: true }).printFile(parse(code, file))
}

const isImportMeta = (n: ts.Node): n is ts.MetaProperty =>
  ts.isMetaProperty(n) && n.keywordToken === ts.SyntaxKind.ImportKeyword && n.name.text === 'meta'

/** 이름으로 읽은 속성 (a.b, a?.b, a['b']). 그 밖의 접근이면 null */
function accessedName(parent: ts.Node, child: ts.Node): string | null {
  if (ts.isPropertyAccessExpression(parent) && parent.expression === child) return parent.name.text
  if (ts.isElementAccessExpression(parent) && parent.expression === child && ts.isStringLiteralLike(parent.argumentExpression))
    return parent.argumentExpression.text
  return null
}

/** import.meta / import.meta.env 를 허용 목록 밖으로 쓰는 곳 */
function envViolations(code: string, file: string): string[] {
  const out: string[] = []
  const visit = (node: ts.Node) => {
    if (isImportMeta(node)) {
      const prop = accessedName(node.parent, node)
      if (prop === 'env') {
        const envNode = node.parent
        const name = accessedName(envNode.parent, envNode)
        // import.meta.env 를 통째로 넘기거나 펼치면(모든 VITE_ 값이 번들에 들어감) 위반
        if (name === null) out.push(`${file}: import.meta.env 를 이름 없이 사용`)
        else if (!BUILTIN.has(name) && !(name in ALLOWED)) out.push(`${file}: import.meta.env.${name}`)
      } else if (prop === null || !META_OK.has(prop)) {
        out.push(`${file}: import.meta${prop ? '.' + prop : ''}`)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(parse(code, file))
  return out
}

const isProcessEnv = (n: ts.Node) =>
  ts.isPropertyAccessExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === 'process' && n.name.text === 'env'

/** vite.config.ts 의 process.env 읽기 중 허용 목록 밖의 것 */
function processEnvViolations(code: string, file: string): string[] {
  const out: string[] = []
  const visit = (node: ts.Node) => {
    if (isProcessEnv(node)) {
      const parent = node.parent
      let name: string | null = accessedName(parent, node)
      // process.env[상수]: 알려진 상수만 실제 이름으로 바꿔 본다
      if (name === null && ts.isElementAccessExpression(parent) && parent.expression === node && ts.isIdentifier(parent.argumentExpression))
        name = CONFIG_ENV_CONSTANTS[parent.argumentExpression.text] ?? null
      if (name === null) out.push(`${file}: process.env 를 이름 없이(또는 알 수 없는 이름으로) 사용`)
      else if (!(name in ALLOWED) && !(name in CONFIG_ONLY)) out.push(`${file}: process.env.${name}`)
    }
    ts.forEachChild(node, visit)
  }
  visit(parse(code, file))
  return out
}

const viteTokens = (code: string) => [...code.matchAll(/\bVITE_[A-Z0-9_]+/g)].map((m) => m[0])

describe('VITE_ 환경변수 허용 목록', () => {
  it('검사할 파일을 읽었다', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20)
    expect(viteConfig).toContain('defineConfig')
    expect(indexHtml).toContain('<div id="root">')
  })

  it('허용 목록은 VITE_ 이름만, 빌드 식별자 변수를 포함한다', () => {
    for (const name of Object.keys(ALLOWED)) expect(name).toMatch(/^VITE_[A-Z0-9_]+$/)
    expect(Object.keys(ALLOWED)).toContain(BUILD_ID_ENV)
  })

  it('앱 소스의 import.meta.env 는 허용된 이름으로만 읽는다', () => {
    const bad = Object.entries(sources).flatMap(([f, c]) => envViolations(c, f))
    expect(bad).toEqual([])
  })

  it('앱 소스·vite.config.ts 에 나오는 VITE_ 이름은 모두 허용 목록에 있다 (주석 제외)', () => {
    const files: [string, string][] = [...Object.entries(sources), ['vite.config.ts', viteConfig]]
    const bad = files.flatMap(([f, c]) =>
      viteTokens(withoutComments(c, f))
        .filter((t) => !(t in ALLOWED))
        .map((t) => `${f}: ${t}`),
    )
    expect(bad).toEqual([])
  })

  it('vite.config.ts 의 process.env 는 허용 목록(공개 값·설정 전용 이름)만 읽는다', () => {
    expect(viteConfig).toContain('process.env')
    expect(processEnvViolations(viteConfig, 'vite.config.ts')).toEqual([])
  })

  it('index.html 의 %이름% 치환은 허용 목록·기본값만', () => {
    const names = [...indexHtml.matchAll(/%([A-Z][A-Z0-9_]*)%/g)].map((m) => m[1])
    expect(names.filter((n) => !BUILTIN.has(n) && !(n in ALLOWED))).toEqual([])
  })

  it('vite.config.ts 가 노출 접두사(envPrefix)나 define 으로 다른 환경변수를 번들에 넣지 않는다', () => {
    const code = withoutComments(viteConfig, 'vite.config.ts')
    expect(code).not.toMatch(/\benvPrefix\b/)
    expect(code).not.toMatch(/\bdefine\s*:/)
    expect(code).not.toMatch(/\bloadEnv\b/)
  })

  it('검사기 자체: 위반을 찾아낸다', () => {
    const probe = [
      'const a = import.meta.env.VITE_SECRET_KEY',
      'const all = import.meta.env',
      "const b = import.meta.env['VITE_OTHER']",
      'const { VITE_X } = import.meta.env',
      'const m = import.meta',
      'const ok1 = import.meta.env.VITE_APP_BUILD_ID',
      'const ok2 = import.meta.env.DEV',
      'const ok3 = import.meta.env?.MODE',
    ].join('\n')
    const v = envViolations(probe, 'probe.ts')
    expect(v).toEqual([
      'probe.ts: import.meta.env.VITE_SECRET_KEY',
      'probe.ts: import.meta.env 를 이름 없이 사용',
      'probe.ts: import.meta.env.VITE_OTHER',
      'probe.ts: import.meta.env 를 이름 없이 사용',
      'probe.ts: import.meta',
    ])
    expect(viteTokens('x // VITE_ 설명\nconst y = "VITE_LEAK"')).toEqual(['VITE_LEAK'])
    const cfgProbe = [
      'const a = process.env.SESSION_SECRET',
      "const b = process.env['ANTHROPIC_API_KEY']",
      'const c = process.env[someName]',
      'const all = { ...process.env }',
      'const ok1 = process.env.VITEST',
      'const ok2 = process.env[BUILD_ID_ENV]',
      "const ok3 = process.env['VITE_APP_BUILD_ID']",
    ].join('\n')
    expect(processEnvViolations(cfgProbe, 'cfg.ts')).toEqual([
      'cfg.ts: process.env.SESSION_SECRET',
      'cfg.ts: process.env.ANTHROPIC_API_KEY',
      'cfg.ts: process.env 를 이름 없이(또는 알 수 없는 이름으로) 사용',
      'cfg.ts: process.env 를 이름 없이(또는 알 수 없는 이름으로) 사용',
    ])
  })
})
