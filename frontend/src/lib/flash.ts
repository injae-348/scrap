// 화면을 옮겨 가며 한 번만 보여 줄 안내 (예: "모든 기기에서 로그아웃했어요" → 로그인 화면).
// 메모리에만 둔다 (브라우저 저장소에 쓰지 않음). 새로고침하면 사라진다.

let pending: string | null = null

export function setFlash(message: string) {
  pending = message
}

/** 지우지 않고 읽는다 (렌더 중 호출용). 보여 준 뒤 clearFlash()로 지운다 */
export function peekFlash(): string | null {
  return pending
}

export function clearFlash() {
  pending = null
}
