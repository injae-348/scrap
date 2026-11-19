import type { Scrap } from '../api/types'
import { useToggleLike } from '../hooks/queries'
import { cx } from '../lib/styles'
import { IconHeart } from './Icons'

export function LikeButton({ scrap, className }: { scrap: Pick<Scrap, 'id' | 'liked'>; className?: string }) {
  const toggle = useToggleLike()
  return (
    <button
      type="button"
      aria-pressed={scrap.liked}
      aria-label={scrap.liked ? '좋아요 취소' : '좋아요'}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        toggle.mutate(scrap)
      }}
      className={cx(
        'inline-flex size-11 shrink-0 items-center justify-center rounded-full transition hover:bg-hover',
        scrap.liked ? 'text-like' : 'text-muted',
        className,
      )}
    >
      <IconHeart size={20} filled={scrap.liked} />
    </button>
  )
}
