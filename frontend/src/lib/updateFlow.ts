// 새 버전(서비스워커) 적용 흐름. 화면(UpdatePrompt)과 분리해 단위 테스트한다.
//
// - 새 버전이 기다리고 있으면(onNeedRefresh) 안내를 띄운다. 자동으로 바꾸지 않는다.
// - 사용자가 "새로고침"을 누르면: 작성 중이면 먼저 확인, 아니면 바로 진행.
//   진행 = 기다리는 워커에 적용 요청. 실제 새로고침은 새 워커가 이 페이지를 제어하게 됐을 때(onNeedReload)만 하고,
//   그 직전에만 이탈 가드를 끈다 (적용할 워커가 없으면 아무것도 바뀌지 않는다).
// - 다른 탭에서 수락해 새 워커가 이 탭을 제어하게 되면(onNeedReload, 이 탭은 수락 안 함) 바로 새로고침하지 않고
//   이 탭에서도 안내를 띄워 따로 동의를 받는다.

export type UpdateView = 'hidden' | 'available' | 'confirm'

export interface UpdateDeps {
  hasActiveGuard: () => boolean
  bypassGuards: () => void
  reload: () => void
}

export function createUpdateController(deps: UpdateDeps, onView: (v: UpdateView) => void) {
  let applyUpdate: (() => Promise<void> | void) | null = null
  /** 새 워커가 이미 이 페이지를 제어 중 (새로고침만 하면 됨) */
  let controlling = false
  /** 이 탭에서 사용자가 새 버전 적용에 동의함 */
  let accepted = false

  const reloadNow = () => {
    deps.bypassGuards()
    deps.reload()
  }
  const proceed = () => {
    if (controlling) {
      reloadNow()
      return
    }
    accepted = true
    void applyUpdate?.()
  }

  return {
    setApplyUpdate(fn: () => Promise<void> | void) {
      applyUpdate = fn
    },
    /** 새 버전이 기다리는 중 */
    onNeedRefresh() {
      onView('available')
    },
    /** 새 워커가 이 페이지를 제어하게 됨 */
    onNeedReload() {
      controlling = true
      if (accepted) reloadNow()
      else onView('available')
    },
    /** "새로고침" 버튼 */
    requestRefresh() {
      if (deps.hasActiveGuard()) onView('confirm')
      else proceed()
    },
    /** 작성 중 확인 창에서 "새로고침" */
    confirm() {
      onView('available')
      proceed()
    },
    /** 작성 중 확인 창에서 "계속 작성" */
    cancel() {
      onView('available')
    },
    /** "나중에" */
    dismiss() {
      onView('hidden')
    },
  }
}
