import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { hastText, linkHostInfo, markdownLinkHref } from '../lib/markdownLinks'
import { displayText } from '../lib/text'

/**
 * 메모 마크다운 렌더링 (렌더링 안전 규칙).
 * - 원시 HTML은 렌더링하지 않는다 (skipHtml, rehype-raw 같은 플러그인 미사용).
 * - 링크는 http/https만 링크로 만들고 새 창 + rel="noopener noreferrer".
 *   그 밖의 스킴(javascript:, data:, vbscript:, mailto:, 상대 경로 등)은 일반 텍스트로 보여 준다.
 * - 이미지는 <img>로 불러오지 않는다 (외부 요청·추적 방지, 운영 CSP도 외부 이미지를 막는다). 링크로만 보여 준다.
 * - 링크 옆에 실제로 열리는 호스트를 작게 보여 준다 (퓨니코드 그대로). 링크 글자가 주소처럼 생겼는데
 *   실제 호스트와 다르면 경고로 보여 준다 (AI가 외부 페이지를 읽고 제안한 메모의 위장 링크 대비).
 * - 렌더링 전에 글자 방향 서식 문자(RLO 등)를 지운다. 링크와 호스트 표시는 각각 <bdi>로 격리한다
 *   (거꾸로 보이게 한 링크 글자·호스트 표시 위장 대비).
 */
export default function MarkdownRenderer({ children }: { children: string }) {
  return (
    <div className="md text-[15px] text-fg">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={(url) => markdownLinkHref(url) ?? ''}
        components={{
          a: ({ href, children, node }) => {
            const safe = typeof href === 'string' ? markdownLinkHref(href) : undefined
            return safe ? (
              <>
                <bdi>
                  <a href={safe} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                </bdi>
                <LinkHost href={safe} text={hastText(node)} />
              </>
            ) : (
              <span>{children}</span>
            )
          },
          img: ({ src, alt }) => {
            const safe = typeof src === 'string' ? markdownLinkHref(src) : undefined
            const label = `[이미지: ${alt || '보기'}]`
            return safe ? (
              <>
                <bdi>
                  <a href={safe} target="_blank" rel="noopener noreferrer">
                    {label}
                  </a>
                </bdi>
                <LinkHost href={safe} text={label} />
              </>
            ) : (
              <span>{label}</span>
            )
          },
        }}
      >
        {displayText(children)}
      </ReactMarkdown>
    </div>
  )
}

/** 링크 바로 뒤에 붙는 실제 호스트 표시. 링크(<a>) 밖에 두어 누르는 영역과 구분한다 */
function LinkHost({ href, text }: { href: string; text: string }) {
  const info = linkHostInfo(href, text)
  if (!info || !info.showHost) return null
  if (info.mismatch)
    return (
      <bdi data-link-host="mismatch" className="ml-1 rounded bg-warn-soft px-1 text-xs font-medium break-all text-warn">
        ⚠ 글자와 다른 주소: {info.host}
      </bdi>
    )
  return (
    <bdi data-link-host="" className="ml-1 text-xs break-all text-muted">
      ({info.host})
    </bdi>
  )
}
