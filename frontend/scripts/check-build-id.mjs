// 빌드 식별자 → 서비스워커 갱신 연결 검사 (외부 의존성 없음: Node 내장 모듈만 사용).
//
//   node scripts/check-build-id.mjs            → dist/ 검사 (npm run build 마지막 단계)
//   node scripts/check-build-id.mjs --compare  → 식별자만 다르게 두 번 빌드해 sw.js 가 달라지는지 확인
//                                                (npm run check:build-id, 임시 폴더에 빌드하고 지운다)
//
// 확인하는 것
//   1. dist/index.html 에 <meta name="app-build" content="…"> 가 있다.
//      환경변수 VITE_APP_BUILD_ID 가 있으면 그 값과 같다.
//   2. dist/sw.js 미리 캐시 목록의 index.html revision 이 index.html 파일 내용의 MD5 와 같다
//      (workbox 의 revision 계산 방식). → 식별자가 바뀌면 revision 과 sw.js 가 함께 바뀐다.
//   3. (--compare) 식별자만 다른 두 빌드의 index.html revision·sw.js 가 서로 다르다.
//
// 실패하면 종료 코드 1. 출력에는 식별자·해시만 쓴다 (비밀값을 다루지 않는다).

import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const ENV = 'VITE_APP_BUILD_ID'

function fail(msg) {
  console.error(`빌드 식별자 검사 실패: ${msg}`)
  process.exit(1)
}

/** dist 폴더를 읽어 식별자·index.html 해시·sw.js 의 index.html revision 을 돌려준다 */
function inspect(dir) {
  let html, sw
  try {
    html = readFileSync(join(dir, 'index.html'))
    sw = readFileSync(join(dir, 'sw.js'), 'utf8')
  } catch {
    fail(`${dir} 에 index.html 또는 sw.js 가 없습니다 (빌드 결과물 확인)`)
  }
  const meta = /<meta\s+name="app-build"\s+content="([^"]*)"\s*\/?>/.exec(html.toString('utf8'))
  if (!meta || !meta[1]) fail('index.html 에 <meta name="app-build"> 가 없습니다')
  // 압축된 sw.js: {url:"index.html",revision:"…"} (키 순서·따옴표 형태가 달라도 찾는다)
  const entry = /\{[^{}]*?["']?url["']?\s*:\s*["']index\.html["'][^{}]*\}/.exec(sw)
  const rev = entry && /["']?revision["']?\s*:\s*["']([0-9a-f]+)["']/.exec(entry[0])
  if (!rev) fail('sw.js 미리 캐시 목록에서 index.html revision 을 찾지 못했습니다')
  return {
    buildId: meta[1],
    htmlMd5: createHash('md5').update(html).digest('hex'),
    revision: rev[1],
    swMd5: createHash('md5').update(sw).digest('hex'),
  }
}

function checkOne(dir, expectedId) {
  const r = inspect(dir)
  if (expectedId && r.buildId !== expectedId) fail(`index.html 식별자(${r.buildId})가 ${ENV}(${expectedId})와 다릅니다`)
  if (r.revision !== r.htmlMd5) fail(`sw.js 의 index.html revision(${r.revision})이 index.html 내용 해시(${r.htmlMd5})와 다릅니다`)
  return r
}

function build(outDir, id) {
  const vite = join(ROOT, 'node_modules', 'vite', 'bin', 'vite.js')
  const res = spawnSync(process.execPath, [vite, 'build', '--outDir', outDir, '--emptyOutDir', '--logLevel', 'error'], {
    cwd: ROOT,
    env: { ...process.env, [ENV]: id, VITEST: '' },
    stdio: 'inherit',
  })
  if (res.status !== 0) fail(`비교용 빌드 실패 (${id})`)
}

if (process.argv.includes('--compare')) {
  const tmp = mkdtempSync(join(tmpdir(), 'scrap-build-id-'))
  try {
    const a = join(tmp, 'a')
    const b = join(tmp, 'b')
    build(a, 'check-a')
    build(b, 'check-b')
    const ra = checkOne(a, 'check-a')
    const rb = checkOne(b, 'check-b')
    if (ra.revision === rb.revision) fail('식별자가 달라도 index.html revision 이 같습니다')
    if (ra.swMd5 === rb.swMd5) fail('식별자가 달라도 sw.js 내용이 같습니다 (브라우저가 새 버전을 감지하지 못함)')
    console.log(`빌드 식별자 비교 통과: index.html revision ${ra.revision.slice(0, 8)} → ${rb.revision.slice(0, 8)}, sw.js 도 달라짐`)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
} else {
  const r = checkOne(join(ROOT, 'dist'), process.env[ENV]?.trim() || undefined)
  console.log(`빌드 식별자 검사 통과: ${r.buildId} (index.html revision ${r.revision.slice(0, 8)})`)
}
