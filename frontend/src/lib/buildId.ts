// 빌드 식별자: 배포마다 index.html에 넣어, 앱 코드가 같은 재배포(헤더만 바꾼 배포 등)에도
// 서비스워커 미리 캐시의 index.html revision(파일 내용 해시)이 바뀌게 한다.
// → sw.js 내용이 바뀌어 브라우저가 새 서비스워커를 받고, 기존 "새 버전이 있어요" 안내가 뜬다.
//
// - 값은 빌드 때 환경변수 VITE_APP_BUILD_ID(커밋 SHA 같은 공개 값)로 받는다. 없으면 빌드 시각으로 대신한다.
// - JS 번들에는 넣지 않는다 (같은 코드면 JS 파일 이름·내용이 그대로여서 브라우저 캐시를 계속 쓴다).
//   화면은 index.html의 <meta name="app-build">를 읽는다.
// - 이 파일은 vite.config.ts(빌드)와 앱(화면) 양쪽에서 쓰므로 Node·DOM 전용 API를 쓰지 않는다.

/** 빌드 식별자를 넘기는 환경변수 이름 (공개 값 전용, VITE_ 규칙) */
export const BUILD_ID_ENV = 'VITE_APP_BUILD_ID'
/** index.html에 넣는 meta 이름 */
export const BUILD_ID_META = 'app-build'

const VALID = /^[A-Za-z0-9._-]{1,64}$/

/**
 * 환경변수 값(없으면 빌드 시각)으로 빌드 식별자를 정한다.
 * 값이 있는데 형식이 맞지 않으면 빌드를 멈춘다 (HTML 속성에 그대로 들어가므로 영문·숫자·`.`·`_`·`-`만, 64자 이하).
 */
export function resolveBuildId(raw: string | undefined, now: Date = new Date()): string {
  const v = raw?.trim()
  if (v) {
    if (!VALID.test(v)) {
      throw new Error(`${BUILD_ID_ENV} 값은 영문·숫자·. _ - 로 된 64자 이하여야 합니다 (예: 커밋 SHA).`)
    }
    return v
  }
  // 예: local-20261121T103000Z
  return 'local-' + now.toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z')
}

/** 화면 표시용: 커밋 SHA(16진수 40자)는 앞 7자만 */
export function shortBuildId(id: string): string {
  return /^[0-9a-f]{40}$/i.test(id) ? id.slice(0, 7) : id
}

/** querySelector만 쓰는 최소 형태 (이 파일은 DOM 타입 없이 vite.config.ts에서도 타입 검사된다) */
interface QueryRoot {
  querySelector(selector: string): { getAttribute(name: string): string | null } | null
}

/** 지금 열린 페이지의 빌드 식별자 (index.html의 meta). 없으면 null. 화면에서는 `currentBuildId(document)` */
export function currentBuildId(doc: QueryRoot): string | null {
  const content = doc.querySelector(`meta[name="${BUILD_ID_META}"]`)?.getAttribute('content')
  return content ? content : null
}
