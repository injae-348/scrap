import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { errorMessage } from '../api/http'
import { IconDevice } from '../components/Icons'
import { ManageList } from '../components/ManageList'
import { Badge, Button, ConfirmButton, ErrorState, Notice, Spinner } from '../components/ui'
import {
  useCreateSource,
  useCreateTopic,
  useDeleteSession,
  useDeleteSource,
  useDeleteTopic,
  useLogout,
  useLogoutAll,
  useReorderSources,
  useReorderTopics,
  useSessions,
  useSources,
  useTopics,
  useUpdateSource,
  useUpdateTopic,
} from '../hooks/queries'
import { formatDateTime, relativeTime } from '../lib/date'
import { parseDomainPatterns } from '../lib/url'
import { describeUserAgent } from '../lib/userAgent'

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      {children}
    </section>
  )
}

const splitPatterns = (s: string) => parseDomainPatterns(s).patterns

function validatePatterns(s: string): string | null {
  const { patterns, invalid } = parseDomainPatterns(s)
  if (invalid.length) return `도메인은 호스트 이름만 입력해 주세요 (예: example.com): ${invalid.join(', ')}`
  if (patterns.length > 20) return '도메인은 출처당 최대 20개까지 넣을 수 있어요.'
  return null
}

export function SettingsPage() {
  const topics = useTopics()
  const sources = useSources()
  const createTopic = useCreateTopic()
  const updateTopic = useUpdateTopic()
  const deleteTopic = useDeleteTopic()
  const reorderTopics = useReorderTopics()
  const createSource = useCreateSource()
  const updateSource = useUpdateSource()
  const deleteSource = useDeleteSource()
  const reorderSources = useReorderSources()
  const defaultName = sources.data?.find((s) => s.is_default)?.name ?? '기본 출처'

  return (
    <div className="lg:h-dvh lg:overflow-y-auto">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/95 pt-safe backdrop-blur">
        <h1 className="mx-auto max-w-2xl px-4 py-3 text-xl font-bold tracking-tight lg:px-8">설정</h1>
      </header>
      <div className="mx-auto max-w-2xl space-y-10 px-4 py-6 lg:px-8">
        <Section title="주제" description="스크랩에 여러 개 붙일 수 있어요. 순서는 목록 필터에 그대로 보여요.">
          {topics.isPending ? (
            <Spinner />
          ) : topics.isError ? (
            <ErrorState message={errorMessage(topics.error)} onRetry={() => topics.refetch()} />
          ) : (
            <ManageList
              items={topics.data.map((t) => ({ id: t.id, name: `#${t.name}` }))}
              addPlaceholder="새 주제 이름"
              emptyText="아직 주제가 없어요. 아래에서 추가해 보세요."
              onAdd={(name) => createTopic.mutateAsync(name.replace(/^#/, ''))}
              onRename={(id, name) => updateTopic.mutateAsync({ id, name })}
              onDelete={(id) => deleteTopic.mutateAsync(id)}
              onReorder={(ids) => reorderTopics.mutateAsync(ids)}
              deleteWarning="주제를 삭제하면 스크랩에서 이 주제만 빠지고 스크랩은 그대로 남아요."
            />
          )}
        </Section>

        <Section title="출처" description={`링크 도메인으로 출처를 자동 판별해요. 맞는 도메인이 없으면 '${defaultName}'(으)로 저장돼요.`}>
          {sources.isPending ? (
            <Spinner />
          ) : sources.isError ? (
            <ErrorState message={errorMessage(sources.error)} onRetry={() => sources.refetch()} />
          ) : (
            <ManageList
              items={sources.data.map((s) => ({
                id: s.id,
                name: s.name,
                detail: [s.is_default && '기본 출처', s.domain_patterns.join(', ') || (!s.is_default && '도메인 없음')]
                  .filter(Boolean)
                  .join(' · '),
                // 기본 출처는 도메인 패턴을 가질 수 없고 삭제할 수 없다
                extra: s.is_default ? undefined : s.domain_patterns.join(', '),
                deletable: !s.is_default,
              }))}
              extraLabel="도메인"
              extraPlaceholder="도메인 (쉼표로 구분, 예: example.com)"
              extraHint="도메인은 호스트 이름만 적어요 (https://·경로 없이). 하위 도메인(www., m.)도 함께 판별돼요."
              validateExtra={validatePatterns}
              addPlaceholder="새 출처 이름"
              emptyText="아직 출처가 없어요. 아래에서 추가해 보세요."
              onAdd={(name, extra) => createSource.mutateAsync({ name, domain_patterns: splitPatterns(extra) })}
              onRename={(id, name, extra) =>
                updateSource.mutateAsync({
                  id,
                  body: extra === undefined ? { name } : { name, domain_patterns: splitPatterns(extra) },
                })
              }
              onDelete={(id) => deleteSource.mutateAsync(id)}
              onReorder={(ids) => reorderSources.mutateAsync(ids)}
              deleteWarning={`출처를 삭제하면 그 출처의 스크랩은 '${defaultName}'(으)로 옮겨져요.`}
            />
          )}
        </Section>

        <Sessions />
        <Account />
      </div>
    </div>
  )
}

function Sessions() {
  const sessions = useSessions()
  const del = useDeleteSession()
  const logoutAll = useLogoutAll()
  const navigate = useNavigate()
  return (
    <Section
      title="로그인된 기기"
      description="마지막 사용 시각은 최대 1시간 정도 늦게 반영될 수 있어요."
    >
      {sessions.isPending ? (
        <Spinner />
      ) : sessions.isError ? (
        <ErrorState message={errorMessage(sessions.error)} onRetry={() => sessions.refetch()} />
      ) : (
        <>
          <ul className="divide-y divide-line rounded-lg border border-line">
            {sessions.data.map((s) => (
              <li key={s.id} className="flex items-center gap-3 py-2 pr-2 pl-3">
                <IconDevice size={20} className="shrink-0 text-muted" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5 text-sm font-medium" title={s.user_agent}>
                    {describeUserAgent(s.user_agent)}
                    {s.current && <Badge tone="accent">지금 쓰는 기기</Badge>}
                  </div>
                  <div className="text-xs text-muted">
                    <span title={formatDateTime(s.last_seen_at)}>마지막 사용 {relativeTime(s.last_seen_at)}</span> ·{' '}
                    <span title={formatDateTime(s.created_at)}>처음 로그인 {relativeTime(s.created_at)}</span>
                  </div>
                </div>
                {!s.current && (
                  <Button
                    variant="ghost"
                    className="text-danger"
                    onClick={() => del.mutate(s.id)}
                    disabled={del.isPending && del.variables === s.id}
                  >
                    로그아웃
                  </Button>
                )}
              </li>
            ))}
          </ul>
          {del.isError && <Notice tone="danger">{errorMessage(del.error)}</Notice>}
          {logoutAll.isError && <Notice tone="danger">{errorMessage(logoutAll.error)}</Notice>}
          <div className="space-y-1.5">
            <ConfirmButton
              label="모든 기기에서 로그아웃"
              confirmLabel="이 기기 포함 모두 로그아웃"
              loading={logoutAll.isPending}
              onConfirm={() =>
                logoutAll.mutate(undefined, {
                  onSuccess: () => navigate('/login', { replace: true }),
                })
              }
            />
            <p className="text-xs text-muted">이 기기도 함께 로그아웃돼요. 휴대폰을 잃어버렸다면 2차 인증 재설정도 해 주세요.</p>
          </div>
        </>
      )}
    </Section>
  )
}

function Account() {
  const logout = useLogout()
  const navigate = useNavigate()
  return (
    <Section title="계정 보안">
      <div className="divide-y divide-line rounded-lg border border-line">
        <Link to="/settings/totp" className="flex min-h-12 items-center justify-between px-3 text-sm hover:bg-hover">
          <span>
            <span className="font-medium">2차 인증 재설정</span>
            <span className="block text-xs text-muted">
              휴대폰을 바꿨을 때 인증 앱을 다시 등록하고 복구 코드를 새로 받아요. 다른 기기는 모두 로그아웃돼요.
            </span>
          </span>
          <span className="text-muted" aria-hidden="true">
            ›
          </span>
        </Link>
      </div>
      {logout.isError && <Notice tone="danger">{errorMessage(logout.error)}</Notice>}
      <Button
        variant="danger"
        loading={logout.isPending}
        onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/login', { replace: true }) })}
      >
        이 기기 로그아웃
      </Button>
    </Section>
  )
}
