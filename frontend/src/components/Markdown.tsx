import { lazy, Suspense } from 'react'

// 마크다운 렌더러(react-markdown + remark-gfm)는 무거워서 필요할 때만 불러온다.
const MarkdownRenderer = lazy(() => import('./MarkdownRenderer'))

export function Markdown({ children }: { children: string }) {
  return (
    <Suspense fallback={<div className="text-sm whitespace-pre-wrap text-muted">{children}</div>}>
      <MarkdownRenderer>{children}</MarkdownRenderer>
    </Suspense>
  )
}
