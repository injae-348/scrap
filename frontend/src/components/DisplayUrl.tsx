import { displayUrl } from '../lib/url'
import { cx } from '../lib/styles'

/**
 * 표시용 URL: 호스트를 굵게 강조하고 나머지는 흐리게. 사용자 정보(user:pass@)는 가린다.
 * 텍스트로만 그린다 (링크 여부는 호출한 쪽이 safeHref로 정한다).
 */
export function DisplayUrl({ url, className }: { url: string; className?: string }) {
  const d = displayUrl(url)
  if (!d.host) return <span className={cx('break-all', className)}>{d.rest}</span>
  return (
    <span className={className}>
      <span className="text-muted">{d.prefix}</span>
      <span className="font-semibold text-fg">{d.host}</span>
      <span className="text-muted">{d.rest}</span>
    </span>
  )
}
