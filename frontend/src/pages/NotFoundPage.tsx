import { Link } from 'react-router'
import { EmptyState } from '../components/ui'

export function NotFoundPage() {
  return (
    <div className="pt-safe">
      <EmptyState
        title="페이지를 찾을 수 없어요"
        action={
          <Link to="/" className="inline-flex min-h-11 items-center rounded-lg border border-line px-4 text-sm hover:bg-hover">
            목록으로
          </Link>
        }
      />
    </div>
  )
}
