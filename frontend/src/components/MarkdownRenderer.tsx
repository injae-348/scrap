import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * 메모 마크다운 렌더링.
 * - raw HTML은 렌더링하지 않는다 (skipHtml, rehype-raw 미사용)
 * - 링크 주소는 http/https/mailto만 허용 (javascript: 등 차단)
 * - 이미지는 외부 요청(추적)을 막기 위해 링크로만 표시
 */
function urlTransform(url: string): string {
  const safe = defaultUrlTransform(url)
  return /^(https?:|mailto:)/i.test(safe) ? safe : ''
}

export default function MarkdownRenderer({ children }: { children: string }) {
  return (
    <div className="md text-[15px] text-fg">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={urlTransform}
        components={{
          a: ({ href, children }) =>
            href ? (
              <a href={href} target="_blank" rel="noopener noreferrer nofollow">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          img: ({ src, alt }) =>
            typeof src === 'string' && src ? (
              <a href={src} target="_blank" rel="noopener noreferrer nofollow">
                [이미지: {alt || '보기'}]
              </a>
            ) : null,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
