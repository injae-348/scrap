/** 아이디 입력칸 공통 속성: 서버는 아이디 대소문자를 구분하므로 iOS 자동 대문자·자동 수정을 끈다 */
export const usernameInputProps = {
  autoComplete: 'username',
  autoCapitalize: 'off',
  autoCorrect: 'off',
  spellCheck: false,
  maxLength: 64,
} as const

