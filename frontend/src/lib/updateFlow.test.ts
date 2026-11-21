import { describe, expect, it, vi } from 'vitest'
import { createUpdateController, type UpdateView } from './updateFlow'

/** 등록 객체 흉내: 기본은 새 워커가 설치돼 기다리는 상태 */
function fakeRegistration() {
  const oldWorker = { state: 'activated' }
  const newWorker = { state: 'installed' }
  return {
    reg: { waiting: newWorker as unknown, active: oldWorker as unknown },
    /** 다른 탭에서 적용해 기다리던 워커가 활성화된 상태로 바꾼다 */
    activateElsewhere(this: { reg: { waiting: unknown; active: unknown } }) {
      newWorker.state = 'activated'
      this.reg.waiting = null
      this.reg.active = newWorker
    },
  }
}

function setup(guard = false, sw = fakeRegistration()) {
  const deps = {
    hasActiveGuard: vi.fn(() => guard),
    bypassGuards: vi.fn(),
    reload: vi.fn(),
    getRegistration: () => sw.reg,
  }
  const views: UpdateView[] = []
  const c = createUpdateController(deps, (v) => views.push(v))
  const apply = vi.fn()
  c.setApplyUpdate(apply)
  return { c, deps, views, apply }
}

describe('새 버전 적용 흐름', () => {
  it('작성 중이 아니면 바로 적용 요청하고, 새 워커가 제어하게 되면 그때 가드를 끄고 새로고침', () => {
    const { c, deps, apply } = setup(false)
    c.onNeedRefresh()
    c.requestRefresh()
    expect(apply).toHaveBeenCalledTimes(1)
    expect(deps.bypassGuards).not.toHaveBeenCalled()
    expect(deps.reload).not.toHaveBeenCalled()
    c.onNeedReload()
    expect(deps.bypassGuards).toHaveBeenCalledTimes(1)
    expect(deps.reload).toHaveBeenCalledTimes(1)
  })

  it('적용할 워커가 없어 제어가 바뀌지 않으면 가드도 그대로', () => {
    const { c, deps } = setup(false)
    c.requestRefresh()
    expect(deps.bypassGuards).not.toHaveBeenCalled()
    expect(deps.reload).not.toHaveBeenCalled()
  })

  it('작성 중이면 먼저 확인 창, "계속 작성"이면 아무것도 하지 않는다', () => {
    const { c, deps, views, apply } = setup(true)
    c.requestRefresh()
    expect(views.at(-1)).toBe('confirm')
    c.cancel()
    expect(apply).not.toHaveBeenCalled()
    expect(deps.bypassGuards).not.toHaveBeenCalled()
    c.requestRefresh()
    c.confirm()
    expect(apply).toHaveBeenCalledTimes(1)
  })

  it('다른 탭에서 수락해 새 워커가 이 탭을 제어해도 이 탭은 동의 전에는 새로고침하지 않는다', () => {
    const { c, deps, views, apply } = setup(true)
    c.onNeedReload()
    expect(deps.reload).not.toHaveBeenCalled()
    expect(views.at(-1)).toBe('available')
    c.requestRefresh()
    expect(views.at(-1)).toBe('confirm')
    c.confirm()
    // 이미 제어 중이므로 적용 요청 없이 새로고침만
    expect(apply).not.toHaveBeenCalled()
    expect(deps.bypassGuards).toHaveBeenCalledTimes(1)
    expect(deps.reload).toHaveBeenCalledTimes(1)
  })

  it('기다리는 워커 없이 새 워커가 이미 활성화돼 있으면 동의 뒤 바로 새로고침한다', () => {
    const sw = fakeRegistration()
    const { c, deps, apply } = setup(false, sw)
    c.onNeedRefresh()
    sw.activateElsewhere()
    c.requestRefresh()
    expect(apply).not.toHaveBeenCalled()
    expect(deps.bypassGuards).toHaveBeenCalledTimes(1)
    expect(deps.reload).toHaveBeenCalledTimes(1)
  })

  it('같은 상황에서 작성 중이면 확인을 먼저 받는다', () => {
    const sw = fakeRegistration()
    const { c, deps, views } = setup(true, sw)
    c.onNeedRefresh()
    sw.activateElsewhere()
    c.requestRefresh()
    expect(views.at(-1)).toBe('confirm')
    expect(deps.reload).not.toHaveBeenCalled()
    c.confirm()
    expect(deps.bypassGuards).toHaveBeenCalledTimes(1)
    expect(deps.reload).toHaveBeenCalledTimes(1)
  })

  it('기다리는 워커가 있으면 바로 새로고침하지 않고 적용 요청만 보낸다', () => {
    const { c, deps, apply } = setup(false)
    c.requestRefresh()
    expect(apply).toHaveBeenCalledTimes(1)
    expect(deps.reload).not.toHaveBeenCalled()
  })
})
