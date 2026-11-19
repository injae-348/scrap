// 아주 작은 전역 토스트 저장소 (짧은 오류·안내 한 줄용). 화면 표시는 components/Toaster.tsx.

export interface ToastItem {
  id: number
  message: string
  tone: 'info' | 'danger'
}

let items: ToastItem[] = []
let seq = 0
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((l) => l())
}

export function showToast(message: string, tone: ToastItem['tone'] = 'info', ms = 3500) {
  const id = ++seq
  // 같은 문구가 연달아 쌓이지 않게 한 개만 유지
  items = [...items.filter((t) => t.message !== message), { id, message, tone }]
  emit()
  setTimeout(() => dismissToast(id), ms)
}

export function dismissToast(id: number) {
  items = items.filter((t) => t.id !== id)
  emit()
}

export const toastStore = {
  subscribe(l: () => void) {
    listeners.add(l)
    return () => {
      listeners.delete(l)
    }
  },
  getSnapshot: () => items,
}
