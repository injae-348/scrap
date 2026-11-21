import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { markdownLinkHref } from '../lib/markdownLinks'

/**
 * 메모 마크다운 렌더링 (렌더링 안전 규칙).
 * - 원시 HTML은 렌더링하지 않는다 (skipHtml, rehype-raw 같은 플러그인 미사용).
 * - 링크는 http/https만 링크로 만들고 새 창 + rel="noopener noreferrer".
 *   그 밖의 스킴(javascript:, data:, vbscript:, mailto:, 상대 경로 등)은 일반 텍스트로 보여 준다.
 * - 이미지는 <img>로 불러오지 않는다 (외부 요청·추적 방지, 운영 CSP도 외부 이미지를 막는다). 링크로만 보여 준다.
 */
export default function MarkdownRenderer({ children }: { children: string }) {
  return (
    <div className="md text-[15px] text-fg">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={(url) => markdownLinkHref(url) ?? ''}
        components={{
          a: ({ href, children }) => {
            const safe = typeof href === 'string' ? markdownLinkHref(href) : undefined
            return safe ? (
              <a href={safe} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            )
          },
          img: ({ src, alt }) => {
            const safe = typeof src === 'string' ? markdownLinkHref(src) : undefined
            const label = `[이미지: ${alt || '보기'}]`
            return safe ? (
              <a href={safe} target="_blank" rel="noopener noreferrer">
                {label}
              </a>
            ) : (
              <span>{label}</span>
            )
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
