import { useState } from 'react'
import { errorMessage } from '../api/http'
import { cx, inputCls } from '../lib/styles'
import { IconDown, IconPencil, IconTrash, IconUp } from './Icons'
import { Button } from './ui'

export interface ManageItem {
  id: number
  name: string
  /** 이름 아래 보조 정보 (출처의 도메인 등) */
  detail?: string
  /** 편집 시 추가 입력값 (출처 도메인 패턴) */
  extra?: string
  locked?: string
}

interface Props {
  items: ManageItem[]
  extraLabel?: string
  extraPlaceholder?: string
  addPlaceholder: string
  /** 항목이 0개일 때 안내 문구 */
  emptyText: string
  onAdd: (name: string, extra: string) => Promise<unknown>
  onRename: (id: number, name: string, extra: string) => Promise<unknown>
  onDelete: (id: number) => Promise<unknown>
  onReorder: (ids: number[]) => Promise<unknown>
  deleteWarning: string
}

/** 주제·출처 관리: 추가, 이름 변경, 삭제, 순서 변경(위/아래 버튼) */
export function ManageList(p: Props) {
  const [editing, setEditing] = useState<number | null>(null)
  const [confirmDel, setConfirmDel] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [newExtra, setNewExtra] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      return true
    } catch (e) {
      setError(errorMessage(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  const move = (idx: number, dir: -1 | 1) => {
    const ids = p.items.map((x) => x.id)
    const j = idx + dir
    if (j < 0 || j >= ids.length) return
    ;[ids[idx], ids[j]] = [ids[j], ids[idx]]
    void run(() => p.onReorder(ids))
  }

  return (
    <div className="space-y-3">
      {p.items.length === 0 && (
        <p className="rounded-lg border border-dashed border-line px-3 py-4 text-center text-sm text-muted">{p.emptyText}</p>
      )}
      <ul className={cx('divide-y divide-line rounded-lg border border-line', p.items.length === 0 && 'hidden')}>
        {p.items.map((it, idx) =>
          editing === it.id ? (
            <EditRow
              key={it.id}
              item={it}
              extraLabel={p.extraLabel}
              extraPlaceholder={p.extraPlaceholder}
              busy={busy}
              onCancel={() => setEditing(null)}
              onSave={async (name, extra) => {
                if (await run(() => p.onRename(it.id, name, extra))) setEditing(null)
              }}
            />
          ) : (
            <li key={it.id} className="flex items-center gap-1 py-1 pr-1 pl-3">
              <div className="min-w-0 flex-1 py-1.5">
                <div className="truncate text-sm font-medium">{it.name}</div>
                {it.detail && <div className="truncate text-xs text-muted">{it.detail}</div>}
              </div>
              {confirmDel === it.id ? (
                <span className="flex items-center gap-1">
                  <Button
                    variant="primary"
                    className="bg-danger! text-bg!"
                    disabled={busy}
                    onClick={async () => {
                      await run(() => p.onDelete(it.id))
                      setConfirmDel(null)
                    }}
                  >
                    삭제
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirmDel(null)}>
                    취소
                  </Button>
                </span>
              ) : (
                <>
                  <Button size="icon" variant="ghost" aria-label={`${it.name} 위로`} disabled={idx === 0 || busy} onClick={() => move(idx, -1)}>
                    <IconUp size={18} />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`${it.name} 아래로`}
                    disabled={idx === p.items.length - 1 || busy}
                    onClick={() => move(idx, 1)}
                  >
                    <IconDown size={18} />
                  </Button>
                  <Button size="icon" variant="ghost" aria-label={`${it.name} 이름 바꾸기`} onClick={() => setEditing(it.id)}>
                    <IconPencil size={18} />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="text-danger"
                    aria-label={`${it.name} 삭제`}
                    title={it.locked}
                    disabled={!!it.locked}
                    onClick={() => setConfirmDel(it.id)}
                  >
                    <IconTrash size={18} />
                  </Button>
                </>
              )}
            </li>
          ),
        )}
      </ul>
      {confirmDel !== null && <p className="text-xs text-muted">{p.deleteWarning}</p>}

      <form
        className="flex flex-wrap gap-2"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!newName.trim()) return
          if (await run(() => p.onAdd(newName, newExtra))) {
            setNewName('')
            setNewExtra('')
          }
        }}
      >
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder={p.addPlaceholder}
          aria-label={p.addPlaceholder}
          className={cx(inputCls, 'min-w-0 flex-1 basis-40')}
          maxLength={30}
        />
        {p.extraLabel && (
          <input
            value={newExtra}
            onChange={(e) => setNewExtra(e.target.value)}
            placeholder={p.extraPlaceholder}
            aria-label={p.extraLabel}
            autoCapitalize="off"
            className={cx(inputCls, 'min-w-0 flex-1 basis-48')}
          />
        )}
        <Button type="submit" variant="secondary" disabled={!newName.trim() || busy}>
          추가
        </Button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  )
}

function EditRow({
  item,
  extraLabel,
  extraPlaceholder,
  busy,
  onCancel,
  onSave,
}: {
  item: ManageItem
  extraLabel?: string
  extraPlaceholder?: string
  busy: boolean
  onCancel: () => void
  onSave: (name: string, extra: string) => void
}) {
  const [name, setName] = useState(item.name)
  const [extra, setExtra] = useState(item.extra ?? '')
  return (
    <li className="p-2">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          onSave(name, extra)
        }}
      >
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="이름"
          className={cx(inputCls, 'min-w-0 flex-1 basis-40')}
          maxLength={30}
        />
        {extraLabel && (
          <input
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
            aria-label={extraLabel}
            placeholder={extraPlaceholder}
            autoCapitalize="off"
            className={cx(inputCls, 'min-w-0 flex-1 basis-48')}
          />
        )}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" loading={busy}>
            저장
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            취소
          </Button>
        </div>
      </form>
    </li>
  )
}
