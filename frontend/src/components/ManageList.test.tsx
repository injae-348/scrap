import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ManageList } from './ManageList'

afterEach(cleanup)

const noop = () => Promise.resolve()

describe('ManageList 이름 수정', () => {
  it('#으로 시작하는 이름도 그대로 수정 칸에 넣는다', () => {
    render(
      <ManageList
        items={[{ id: 1, name: '#해시출처' }]}
        addPlaceholder="새 출처 이름"
        emptyText="없음"
        onAdd={noop}
        onRename={noop}
        onDelete={noop}
        onReorder={noop}
        deleteWarning=""
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '#해시출처 수정' }))
    expect((screen.getByLabelText('이름') as HTMLInputElement).value).toBe('#해시출처')
  })

  it('editName이 있으면 그 값으로 수정을 시작하고 저장한다', async () => {
    const onRename = vi.fn(noop)
    render(
      <ManageList
        items={[{ id: 2, name: '#claude', editName: 'claude' }]}
        addPlaceholder="새 주제 이름"
        emptyText="없음"
        onAdd={noop}
        onRename={onRename}
        onDelete={noop}
        onReorder={noop}
        deleteWarning=""
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '#claude 수정' }))
    const input = screen.getByLabelText('이름') as HTMLInputElement
    expect(input.value).toBe('claude')
    fireEvent.submit(input.closest('form')!)
    await vi.waitFor(() => expect(onRename).toHaveBeenCalledWith(2, 'claude', undefined))
  })
})
