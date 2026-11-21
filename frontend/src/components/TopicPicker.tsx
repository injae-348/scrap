import { useState } from 'react'
import { errorMessage } from '../api/http'
import type { Topic } from '../api/types'
import { useCreateTopic } from '../hooks/queries'
import { cx, inputCls } from '../lib/styles'
import { IconCheck, IconPlus, IconSparkles } from './Icons'
import { Button, Chip } from './ui'
import { displayText } from '../lib/text'

/** 주제 다중 선택 + 새 주제 추가 + AI 추천 주제 표시 */
export function TopicPicker({
  topics,
  selected,
  onChange,
  aiSuggestedIds,
  aiNewNames,
  onDismissNewName,
}: {
  topics: Topic[]
  selected: number[]
  onChange: (ids: number[]) => void
  aiSuggestedIds: number[]
  aiNewNames: string[]
  onDismissNewName: (name: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const create = useCreateTopic()

  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id])

  const add = (n: string, after?: () => void) => {
    const trimmed = n.trim()
    if (!trimmed) return
    const existing = topics.find((t) => t.name.toLowerCase() === trimmed.toLowerCase())
    if (existing) {
      if (!selected.includes(existing.id)) onChange([...selected, existing.id])
      after?.()
      return
    }
    create.mutate(trimmed, {
      onSuccess: (t) => {
        onChange([...selected, t.id])
        after?.()
      },
    })
  }

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap gap-2">
        {topics.map((t) => {
          const on = selected.includes(t.id)
          return (
            <Chip key={t.id} active={on} onClick={() => toggle(t.id)}>
              {on && <IconCheck size={14} />}#{displayText(t.name)}
              {aiSuggestedIds.includes(t.id) && <IconSparkles size={13} aria-label="AI 추천" className="text-accent" />}
            </Chip>
          )
        })}
        {!adding && (
          <Chip onClick={() => setAdding(true)} className="border-dashed">
            <IconPlus size={14} />새 주제
          </Chip>
        )}
      </div>

      {aiNewNames.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-accent/40 p-2.5">
          <span className="inline-flex items-center gap-1 text-xs font-medium text-accent">
            <IconSparkles size={14} />
            AI가 제안한 새 주제
          </span>
          {aiNewNames.map((n) => (
            <span key={n} className="inline-flex items-center gap-1">
              <Chip onClick={() => add(n, () => onDismissNewName(n))} aria-label={`새 주제 ${n} 추가`}>
                <IconPlus size={14} />#{n}
              </Chip>
              <button
                type="button"
                className="min-h-11 px-1.5 text-xs text-muted hover:text-fg lg:min-h-9"
                onClick={() => onDismissNewName(n)}
                aria-label={`${n} 제안 무시`}
              >
                무시
              </button>
            </span>
          ))}
        </div>
      )}

      {adding && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            add(name, () => {
              setName('')
              setAdding(false)
            })
          }}
        >
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="새 주제 이름"
            aria-label="새 주제 이름"
            className={cx(inputCls, 'flex-1')}
            maxLength={30}
          />
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>
            추가
          </Button>
          <Button variant="ghost" onClick={() => setAdding(false)}>
            취소
          </Button>
        </form>
      )}
      {create.isError && <p className="text-sm text-danger">{errorMessage(create.error)}</p>}
    </div>
  )
}
