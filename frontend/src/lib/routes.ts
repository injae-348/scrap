/** 편집 화면 경로인지 (/scraps/new, /scraps/:id/edit — 앞에 /liked 등 목록 경로가 붙을 수 있다) */
export function isEditPath(pathname: string): boolean {
  return /\/scraps\/(new|\d+\/edit)\/?$/.test(pathname)
}
