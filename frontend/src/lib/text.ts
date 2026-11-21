// 화면 표시용 텍스트 정리.

/** 글자 방향을 바꾸는 서식 문자 (LRE·RLE·PDF·LRO·RLO, LRI·RLI·FSI·PDI, LRM·RLM, ALM) */
export const BIDI_CONTROL_RE = /[‪-‮⁦-⁩‎‏؜]/g

/** 표시 전에 글자 방향 서식 문자를 지운다 (제목·메모 미리보기·이름 등 사용자·원격 입력 텍스트) */
export function displayText(s: string): string {
  return s.replace(BIDI_CONTROL_RE, '')
}
