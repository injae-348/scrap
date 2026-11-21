import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { LeaveDialog } from './ui'

afterEach(cleanup)

function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        열기
      </button>
      <button type="button">배경 버튼</button>
      <LeaveDialog open={open} onStay={() => setOpen(false)} onLeave={() => setOpen(false)} />
    </div>
  )
}

describe('LeaveDialog 포커스', () => {
  it('열리면 안쪽에 포커스, Tab은 안에서만 돌고, 닫히면 연 버튼으로 돌아간다', () => {
    render(<Harness />)
    const opener = screen.getByRole('button', { name: '열기' })
    opener.focus()
    fireEvent.click(opener)
    const stay = screen.getByRole('button', { name: '계속 작성' })
    const leave = screen.getByRole('button', { name: '나가기' })
    expect(document.activeElement).toBe(stay)
    // 마지막 버튼에서 Tab → 첫 버튼
    fireEvent.keyDown(stay, { key: 'Tab' })
    expect(document.activeElement).toBe(leave)
    // 첫 버튼에서 Shift+Tab → 마지막 버튼
    fireEvent.keyDown(leave, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(stay)
    // Esc → 닫힘, 포커스 복원
    fireEvent.keyDown(stay, { key: 'Escape' })
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(document.activeElement).toBe(opener)
  })

  it('onLeave가 없으면 나가기 버튼을 숨긴다', () => {
    render(<LeaveDialog open onStay={() => {}} />)
    expect(screen.queryByRole('button', { name: '나가기' })).toBeNull()
  })
})
