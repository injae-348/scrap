/** 편집 화면 경로인지 (/scraps/new, /scraps/:id/edit — 앞에 /liked 등 목록 경로가 붙을 수 있다) */
export function isEditPath(pathname: string): boolean {
  return /\/scraps\/(new|\d+\/edit)\/?$/.test(pathname)
}

/**
 * 세션이 만료돼도 화면을 남겨 두는 경로: 작성 중인 편집 폼, 2차 인증 재설정(복구 코드는 한 번만 표시되므로).
 * 최초 가입 화면은 AppLayout 밖이라 해당하지 않는다.
 */
export function keepsScreenOnExpiry(pathname: string): boolean {
  return isEditPath(pathname) || /^\/settings\/totp\/?$/.test(pathname)
}
