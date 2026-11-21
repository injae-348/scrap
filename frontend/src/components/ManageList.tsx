import { useState } from 'react'
import { errorMessage, isApiError } from '../api/http'
import { cx, inputCls } from '../lib/styles'
import { IconDown, IconPencil, IconTrash, IconUp } from './Icons'
import { Button } from './ui'
import { displayText } from '../lib/text'

export interface ManageItem {
  id: number
  name: string
  /** 이름 수정 칸의 처음 값. 없으면 name (주제는 표시용 '#'을 뺀 값을 넘긴다) */
  editName?: string
  /** 이름 아래 보조 정보 (출처의 도메인 등) */
  detail?: string
  /** 편집 시 추가 입력값 (출처 도메인 패턴). undefined면 추가 입력칸을 보이지 않는다 */
  extra?: string
  /** false면 삭제 버튼을 숨긴다 (기본 출처) */
  deletable?: boolean
}

interface FieldErrors {
  name?: string
  extra?: string
  general?: string
}

interface Props {
  items: ManageItem[]
  extraLabel?: string
  extraPlaceholder?: string
  extraHint?: string
  addPlaceholder: string
  /** 항목이 0개일 때 안내 문구 */
  emptyText: string
  /** 추가 입력값을 보내기 전에 검사. 문제가 있으면 문구를 돌려준다 */
  validateExtra?: (extra: string) => string | null
  onAdd: (name: string, extra: string) => Promise<unknown>
  onRename: (id: number, name: string, extra: string | undefined) => Promise<unknown>
  onDelete: (id: number) => Promise<unknown>
  onReorder: (ids: number[]) => Promise<unknown>
  deleteWarning: string
}

/** 서버 오류를 입력칸별 오류로 나눈다: 이름 중복은 이름 칸, 패턴 중복은 도메인 칸 */
function toFieldErrors(e: unknown): FieldErrors {
  if (isApiError(e, 'duplicate_name')) return { name: errorMessage(e) }
  if (isApiError(e, 'duplicate_pattern')) return { extra: errorMessage(e) }
  return { general: errorMessage(e) }
}

/** 주제·출처 관리: 추가, 이름 변경, 삭제, 순서 변경(위/아래 버튼) */
export function ManageList(p: Props) {
  const [editing, setEditing] = useState<number | null>(null)
  const [confirmDel, setConfirmDel] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [newExtra, setNewExtra] = useState('')
  const [addErrors, setAddErrors] = useState<FieldErrors>({})
  const [listError, setListError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const runList = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setListError(null)
    try {
      await fn()
      return true
    } catch (e) {
      setListError(errorMessage(e))
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
    void runList(() => p.onReorder(ids))
  }

  const submitAdd = async () => {
    const name = newName.trim()
    if (!name) return
    const extraErr = p.extraLabel && p.validateExtra ? p.validateExtra(newExtra) : null
    if (extraErr) {
      setAddErrors({ extra: extraErr })
      return
    }
    setBusy(true)
    setAddErrors({})
    try {
      await p.onAdd(name, newExtra)
      setNewName('')
      setNewExtra('')
    } catch (e) {
      setAddErrors(toFieldErrors(e))
    } finally {
      setBusy(false)
    }
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
              extraLabel={it.extra !== undefined ? p.extraLabel : undefined}
              extraPlaceholder={p.extraPlaceholder}
              validateExtra={p.validateExtra}
              onCancel={() => setEditing(null)}
              onSave={async (name, extra) => {
                await p.onRename(it.id, name, extra)
                setEditing(null)
              }}
            />
          ) : (
            <li key={it.id} className="flex items-center gap-1 py-1 pr-1 pl-3">
              <div className="min-w-0 flex-1 py-1.5">
                <div className="truncate text-sm font-medium">{displayText(it.name)}</div>
                {it.detail && <div className="truncate text-xs text-muted">{it.detail}</div>}
              </div>
              {confirmDel === it.id ? (
                <span className="flex items-center gap-1">
                  <Button
                    variant="primary"
                    className="bg-danger! text-bg!"
                    disabled={busy}
                    onClick={async () => {
                      await runList(() => p.onDelete(it.id))
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
                  <Button size="icon" variant="ghost" aria-label={`${it.name} 수정`} onClick={() => setEditing(it.id)}>
                    <IconPencil size={18} />
                  </Button>
                  {it.deletable !== false ? (
                    <Button
                      size="icon"
                      variant="ghost"
                      className="text-danger"
                      aria-label={`${it.name} 삭제`}
                      onClick={() => setConfirmDel(it.id)}
                    >
                      <IconTrash size={18} />
                    </Button>
                  ) : (
                    <span className="size-11 shrink-0" aria-hidden="true" />
                  )}
                </>
              )}
            </li>
          ),
        )}
      </ul>
      {confirmDel !== null && <p className="text-xs text-muted">{p.deleteWarning}</p>}
      {listError && (
        <p role="alert" className="text-sm text-danger">
          {listError}
        </p>
      )}

      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault()
          void submitAdd()
        }}
      >
        <div className="flex flex-wrap gap-2">
          <input
            value={newName}
            onChange={(e) => {
              setNewName(e.target.value)
              setAddErrors((x) => ({ ...x, name: undefined }))
            }}
            placeholder={p.addPlaceholder}
            aria-label={p.addPlaceholder}
            aria-invalid={!!addErrors.name || undefined}
            className={cx(inputCls, 'min-w-0 flex-1 basis-40', addErrors.name && 'border-danger')}
            maxLength={30}
          />
          {p.extraLabel && (
            <input
              value={newExtra}
              onChange={(e) => {
                setNewExtra(e.target.value)
                setAddErrors((x) => ({ ...x, extra: undefined }))
              }}
              placeholder={p.extraPlaceholder}
              aria-label={p.extraLabel}
              aria-invalid={!!addErrors.extra || undefined}
              inputMode="url"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className={cx(inputCls, 'min-w-0 flex-1 basis-48', addErrors.extra && 'border-danger')}
            />
          )}
          <Button type="submit" variant="secondary" disabled={!newName.trim()} loading={busy}>
            추가
          </Button>
        </div>
        {p.extraHint && <p className="text-xs text-muted">{p.extraHint}</p>}
        <FieldErrorList errors={addErrors} />
      </form>
    </div>
  )
}

function FieldErrorList({ errors }: { errors: FieldErrors }) {
  const list = [errors.name, errors.extra, errors.general].filter(Boolean)
  if (!list.length) return null
  return (
    <div role="alert" className="space-y-1">
      {list.map((m) => (
        <p key={m} className="text-sm text-danger">
          {m}
        </p>
      ))}
    </div>
  )
}

function EditRow({
  item,
  extraLabel,
  extraPlaceholder,
  validateExtra,
  onCancel,
  onSave,
}: {
  item: ManageItem
  extraLabel?: string
  extraPlaceholder?: string
  validateExtra?: (extra: string) => string | null
  onCancel: () => void
  onSave: (name: string, extra: string | undefined) => Promise<void>
}) {
  const [name, setName] = useState(item.editName ?? item.name)
  const [extra, setExtra] = useState(item.extra ?? '')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [busy, setBusy] = useState(false)
  return (
    <li className="p-2">
      <form
        className="space-y-2"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!name.trim()) return setErrors({ name: '이름을 입력해 주세요.' })
          const extraErr = extraLabel && validateExtra ? validateExtra(extra) : null
          if (extraErr) return setErrors({ extra: extraErr })
          setBusy(true)
          setErrors({})
          try {
            await onSave(name.trim(), extraLabel ? extra : undefined)
          } catch (err) {
            setErrors(toFieldErrors(err))
            setBusy(false)
          }
        }}
      >
        <div className="flex flex-wrap gap-2">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="이름"
            aria-invalid={!!errors.name || undefined}
            className={cx(inputCls, 'min-w-0 flex-1 basis-40', errors.name && 'border-danger')}
            maxLength={30}
          />
          {extraLabel && (
            <input
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              aria-label={extraLabel}
              aria-invalid={!!errors.extra || undefined}
              placeholder={extraPlaceholder}
              inputMode="url"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className={cx(inputCls, 'min-w-0 flex-1 basis-48', errors.extra && 'border-danger')}
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
        </div>
        <FieldErrorList errors={errors} />
      </form>
    </li>
  )
}
