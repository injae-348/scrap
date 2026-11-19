import { useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
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
import { relativeTime } from '../lib/date'
import { mockDev } from '../mocks/server'
import { DEFAULT_SOURCE_ID } from '../mocks/data'

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

const splitPatterns = (s: string) =>
  s
    .split(/[,\s]+/)
    .map((x) => x.trim().toLowerCase())
    .filter(Boolean)

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
              items={topics.data.map((t) => ({ id: t.id, name: `#${t.name}`, extra: undefined }))}
              addPlaceholder="새 주제 이름"
              onAdd={(name) => createTopic.mutateAsync(name.replace(/^#/, ''))}
              onRename={(id, name) => updateTopic.mutateAsync({ id, name: name.replace(/^#/, '') })}
              onDelete={(id) => deleteTopic.mutateAsync(id)}
              onReorder={(ids) => reorderTopics.mutateAsync(ids)}
              deleteWarning="주제를 삭제하면 스크랩에서 이 주제만 빠지고 스크랩은 그대로 남아요."
            />
          )}
        </Section>

        <Section title="출처" description="링크 도메인으로 출처를 자동 판별해요. 맞는 도메인이 없으면 '일반사이트'가 돼요.">
          {sources.isPending ? (
            <Spinner />
          ) : sources.isError ? (
            <ErrorState message={errorMessage(sources.error)} onRetry={() => sources.refetch()} />
          ) : (
            <ManageList
              items={sources.data.map((s) => ({
                id: s.id,
                name: s.name,
                detail: s.domain_patterns.length ? s.domain_patterns.join(', ') : '도메인 없음 (기본 출처)',
                extra: s.domain_patterns.join(', '),
                locked: s.id === DEFAULT_SOURCE_ID ? '기본 출처는 삭제할 수 없어요' : undefined,
              }))}
              extraLabel="도메인"
              extraPlaceholder="도메인 (쉼표로 구분, 예: example.com)"
              addPlaceholder="새 출처 이름"
              onAdd={(name, extra) => createSource.mutateAsync({ name, domain_patterns: splitPatterns(extra) })}
              onRename={(id, name, extra) =>
                updateSource.mutateAsync({ id, body: { name, domain_patterns: splitPatterns(extra) } })
              }
              onDelete={(id) => deleteSource.mutateAsync(id)}
              onReorder={(ids) => reorderSources.mutateAsync(ids)}
              deleteWarning="출처를 삭제하면 그 출처의 스크랩은 '일반사이트'로 옮겨져요."
            />
          )}
        </Section>

        <Sessions />
        <Account />
        <DevTools />
      </div>
    </div>
  )
}

function Sessions() {
  const sessions = useSessions()
  const del = useDeleteSession()
  const logoutAll = useLogoutAll()
  return (
    <Section title="로그인된 기기">
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
                  <div className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                    {s.user_agent}
                    {s.current && <Badge tone="accent">이 기기</Badge>}
                  </div>
                  <div className="text-xs text-muted">
                    마지막 사용 {relativeTime(s.last_seen_at)} · 처음 로그인 {relativeTime(s.created_at)}
                  </div>
                </div>
                {!s.current && (
                  <Button variant="ghost" className="text-danger" onClick={() => del.mutate(s.id)} disabled={del.isPending}>
                    로그아웃
                  </Button>
                )}
              </li>
            ))}
          </ul>
          {logoutAll.isSuccess && <Notice tone="ok">이 기기를 뺀 모든 기기에서 로그아웃했어요.</Notice>}
          {sessions.data.some((s) => !s.current) && (
            <ConfirmButton
              label="다른 기기 모두 로그아웃"
              confirmLabel="모두 로그아웃"
              loading={logoutAll.isPending}
              onConfirm={() => logoutAll.mutate()}
            />
          )}
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
            <span className="block text-xs text-muted">휴대폰을 바꿨을 때 인증 앱을 다시 등록하고 복구 코드를 새로 받아요.</span>
          </span>
          <span className="text-muted" aria-hidden="true">
            ›
          </span>
        </Link>
      </div>
      <Button
        variant="danger"
        loading={logout.isPending}
        onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/login', { replace: true }) })}
      >
        로그아웃
      </Button>
    </Section>
  )
}

/** 목 단계 전용. Phase 6에서 실제 API로 바꿀 때 지운다. */
function DevTools() {
  const qc = useQueryClient()
  const [, force] = useState(0)
  const f = mockDev.flags
  const refresh = () => {
    force((n) => n + 1)
    void qc.invalidateQueries()
  }
  const toggle = (label: string, checked: boolean, onChange: (v: boolean) => void) => (
    <label className="flex min-h-11 items-center gap-3 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => {
          onChange(e.target.checked)
          refresh()
        }}
        className="size-5 accent-[var(--c-accent-solid)]"
      />
      {label}
    </label>
  )
  return (
    <Section title="개발용 (목 데이터)" description="Phase 1 확인용입니다. 실제 API 연동 때 없어져요.">
      <div className="rounded-lg border border-dashed border-line px-3 py-1">
        {toggle('스크랩 0개 (빈 상태)', f.empty, (v) => mockDev.setEmpty(v))}
        {toggle('목록 불러오기 실패', f.fail.has('list'), (v) => mockDev.setFail('list', v))}
        {toggle('AI 채우기·AI 검색 실패', f.fail.has('ai'), (v) => mockDev.setFail('ai', v))}
        {toggle('저장 실패', f.fail.has('save'), (v) => mockDev.setFail('save', v))}
        {toggle('느린 응답 (로딩 확인)', f.slow, (v) => mockDev.setSlow(v))}
      </div>
      <p className="text-xs text-muted">
        주소로도 켤 수 있어요: <code>?empty=1</code>, <code>?fail=list,ai,save</code>, <code>?slow=1</code>,{' '}
        <code>?auth=login</code>, <code>?auth=setup</code> (새로고침하면 목 데이터는 처음 상태로 돌아가요)
      </p>
      <div className="flex flex-wrap gap-2 text-sm">
        <Link to="/setup" className="inline-flex min-h-11 items-center rounded-lg border border-line px-3 hover:bg-hover">
          가입 화면 보기
        </Link>
        <Link to="/login" className="inline-flex min-h-11 items-center rounded-lg border border-line px-3 hover:bg-hover">
          로그인 화면 보기
        </Link>
      </div>
    </Section>
  )
}
