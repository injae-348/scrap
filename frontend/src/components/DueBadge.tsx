import { dueLabel, dueStatus } from '../lib/date'
import { Badge } from './ui'
import { IconClock } from './Icons'

export function DueBadge({ due }: { due: string | null }) {
  const st = dueStatus(due)
  if (!due || !st) return null
  const tone = st === 'past' ? 'danger' : st === 'soon' ? 'warn' : 'muted'
  const label = st === 'past' ? `마감 ${dueLabel(due)}` : st === 'soon' ? dueLabel(due) : `${dueLabel(due)} 마감`
  return (
    <Badge tone={tone}>
      <IconClock size={12} />
      {label}
    </Badge>
  )
}
