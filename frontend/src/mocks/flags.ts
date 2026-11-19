// 목 단계 전용 설정. 처음 열 때의 URL 쿼리로 켤 수 있고, 설정 화면의 "개발용" 섹션에서도 바꿀 수 있다.
//   ?empty=1        스크랩 0개 상태로 시작
//   ?fail=list      목록 API 실패
//   ?fail=ai        AI 채우기·AI 검색 실패
//   ?fail=save      저장 실패
//   ?auth=login     로그아웃 상태로 시작
//   ?auth=setup     가입 전(사용자 0명) 상태로 시작
//   ?slow=1         지연을 1.5초로 늘림 (로딩 화면 확인용)

export type FailTarget = 'list' | 'ai' | 'save'

const params = new URLSearchParams(window.location.search)

export const mockFlags = {
  empty: params.get('empty') === '1',
  fail: new Set<FailTarget>(
    (params.get('fail') ?? '')
      .split(',')
      .filter((s): s is FailTarget => s === 'list' || s === 'ai' || s === 'save'),
  ),
  slow: params.get('slow') === '1',
  auth: params.get('auth'),
}
