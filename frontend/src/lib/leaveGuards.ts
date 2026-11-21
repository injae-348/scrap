// 지금 켜져 있는 이탈 가드(작성 중 경고) 목록. 새로고침처럼 라우터 밖에서 페이지를 바꾸는 동작이 확인할 때 쓴다.

interface Guard {
  /** 이 가드의 이탈 확인(beforeunload 포함)을 끈다 */
  bypass: () => void
}

const active = new Set<Guard>()

export function registerLeaveGuard(g: Guard): () => void {
  active.add(g)
  return () => {
    active.delete(g)
  }
}

export function hasActiveLeaveGuard(): boolean {
  return active.size > 0
}

/** 사용자가 나가기로 정했을 때: 모든 가드의 확인을 끈다 */
export function bypassAllLeaveGuards() {
  for (const g of active) g.bypass()
}
