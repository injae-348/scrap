import {
  QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query'
import { authApi, scrapsApi, sourcesApi, topicsApi } from '../api'
import { ApiError, errorMessage, setUnauthorizedHandler } from '../api/http'
import type {
  AuthStatus,
  Scrap,
  ScrapCreate,
  ScrapListParams,
  ScrapListResponse,
  ScrapPatch,
  SourceInput,
} from '../api/types'
import { setFlash } from '../lib/flash'
import { showToast } from '../lib/toast'

export const keys = {
  authStatus: ['auth', 'status'] as const,
  sessions: ['auth', 'sessions'] as const,
  scraps: ['scraps'] as const,
  scrapLists: ['scraps', 'list'] as const,
  scrapList: (p: ScrapListParams) => ['scraps', 'list', p] as const,
  scrap: (id: number) => ['scraps', 'detail', id] as const,
  sources: ['sources'] as const,
  topics: ['topics'] as const,
}

/** 화면 쪽에서 쓰는 인증 상태. expired는 사용 중 세션이 만료된 경우(프론트 전용 표시) */
export type ClientAuthStatus = AuthStatus & {
  expired?: boolean
  /** 만료 뒤에도 401이 올 때마다 늘린다 (화면이 다시 로그인으로 보내게) */
  expiredSeq?: number
}

/** 네트워크 오류·일시적 서버 오류만 한 번 더 시도한다 (401·400 같은 응답은 다시 보내도 같다) */
function shouldRetry(failureCount: number, err: unknown): boolean {
  if (failureCount >= 1) return false
  if (!(err instanceof ApiError)) return false
  return err.status === 0 || err.status === 502 || err.status === 503 || err.status === 504
}

export function createQueryClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
  // 401 unauthorized(세션 없음·만료) → 로그인 필요 상태로 바꾼다. 화면 이동은 AppLayout이 맡는다
  // (작성 중인 내용이 있으면 이탈 경고를 거친다).
  // 캐시는 여기서 비우지 않는다 (편집 화면이 로딩으로 바뀌어 작성 중인 내용이 사라지지 않게). 로그인 화면이 비운다.
  setUnauthorizedHandler(() => {
    const prev = qc.getQueryData<ClientAuthStatus>(keys.authStatus)
    if (prev && !prev.logged_in && !prev.expired) return
    qc.setQueryData<ClientAuthStatus>(keys.authStatus, {
      setup_required: false,
      logged_in: false,
      expired: true,
      expiredSeq: (prev?.expiredSeq ?? 0) + 1,
    })
  })
  return qc
}

/** 로그인·로그아웃 때 이전 사용자의 캐시(스크랩·출처·주제·기기 목록)를 비운다 */
export function clearPrivateCache(qc: QueryClient) {
  qc.removeQueries({ predicate: (q) => !(q.queryKey[0] === 'auth' && q.queryKey[1] === 'status') })
}

export function useAuthStatus() {
  return useQuery<ClientAuthStatus>({ queryKey: keys.authStatus, queryFn: authApi.status, staleTime: 60_000 })
}

/**
 * 스크랩 목록. 필터·정렬·검색어가 queryKey에 들어가므로 바뀌면 새 목록을 처음부터 받는다 (이전 커서는 버림).
 * 다음 페이지는 서버가 준 next_cursor를 그대로 보낸다.
 */
export function useScrapList(p: Omit<ScrapListParams, 'cursor' | 'limit'>) {
  return useInfiniteQuery({
    queryKey: keys.scrapList(p),
    queryFn: ({ pageParam }) => scrapsApi.list({ ...p, cursor: pageParam ?? undefined }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
}

/** 상세(메모 전문). 목록 데이터로 채우지 않고 항상 GET /scraps/{id}로 받는다 */
export function useScrap(id: number, opts?: { fresh?: boolean }) {
  return useQuery({
    queryKey: keys.scrap(id),
    queryFn: () => scrapsApi.get(id),
    enabled: Number.isInteger(id) && id > 0,
    refetchOnMount: opts?.fresh ? 'always' : true,
  })
}

export function useSources() {
  return useQuery({ queryKey: keys.sources, queryFn: sourcesApi.list, staleTime: 5 * 60_000 })
}

export function useTopics() {
  return useQuery({ queryKey: keys.topics, queryFn: topicsApi.list, staleTime: 5 * 60_000 })
}

export function useSessions() {
  return useQuery({ queryKey: keys.sessions, queryFn: authApi.sessions })
}

export function useSaveScrap() {
  const qc = useQueryClient()
  return useMutation({
    // 생성은 POST, 수정은 PATCH(바뀐 필드만, liked 없음 — 좋아요는 PUT /like로만)
    mutationFn: (v: { id: number; body: ScrapPatch } | { id?: undefined; body: ScrapCreate }) =>
      v.id !== undefined ? scrapsApi.update(v.id, v.body) : scrapsApi.create(v.body),
    onSuccess: (saved) => {
      qc.setQueryData(keys.scrap(saved.id), saved)
      return qc.invalidateQueries({ queryKey: keys.scrapLists })
    },
  })
}

export function useDeleteScrap() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => scrapsApi.remove(id),
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: keys.scrap(id) })
      return qc.invalidateQueries({ queryKey: keys.scrapLists })
    },
  })
}

/** 좋아요 — 화면은 즉시 바꾸고(낙관적 업데이트), 실패하면 되돌리고 짧게 안내한다 */
export function useToggleLike() {
  const qc = useQueryClient()
  const patch = (id: number, liked: boolean) => {
    qc.setQueriesData<InfiniteData<ScrapListResponse>>({ queryKey: keys.scrapLists }, (old) =>
      old?.pages
        ? {
            ...old,
            pages: old.pages.map((pg) => ({
              ...pg,
              items: pg.items.map((s) => (s.id === id ? { ...s, liked } : s)),
            })),
          }
        : old,
    )
    qc.setQueryData<Scrap>(keys.scrap(id), (old) => (old ? { ...old, liked } : old))
  }
  return useMutation({
    // PUT /scraps/{id}/like { liked } — 원하는 값을 지정하므로 연타·재시도해도 결과가 같다
    mutationFn: (s: { id: number; liked: boolean }) => scrapsApi.setLike(s.id, !s.liked),
    onMutate: (s) => patch(s.id, !s.liked),
    onError: (e, s) => {
      patch(s.id, s.liked)
      if (e instanceof ApiError && e.code === 'unauthorized') return
      const specific = e instanceof ApiError && (e.status === 0 || e.status === 404 || e.status === 429)
      showToast(specific ? errorMessage(e) : '좋아요를 바꾸지 못했어요. 잠시 후 다시 시도해 주세요.', 'danger')
    },
    onSuccess: (res, s) => {
      patch(s.id, res.liked)
      // 좋아요 보기 목록은 항목이 들어오고 빠지므로 다시 받는다
      void qc.invalidateQueries({ queryKey: keys.scrapLists, refetchType: 'inactive' })
    },
  })
}

function useInvalidating<TVars, TRes>(fn: (v: TVars) => Promise<TRes>, invalidate: readonly (readonly unknown[])[]) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(invalidate.map((k) => qc.invalidateQueries({ queryKey: k }))),
  })
}

export function useCreateTopic() {
  return useInvalidating((name: string) => topicsApi.create({ name }), [keys.topics])
}
export function useUpdateTopic() {
  return useInvalidating((v: { id: number; name: string }) => topicsApi.update(v.id, { name: v.name }), [
    keys.topics,
    keys.scraps,
  ])
}
export function useDeleteTopic() {
  return useInvalidating((id: number) => topicsApi.remove(id), [keys.topics, keys.scraps])
}
export function useReorderTopics() {
  return useInvalidating((ids: number[]) => topicsApi.reorder(ids), [keys.topics, keys.scraps])
}

export function useCreateSource() {
  return useInvalidating((v: SourceInput) => sourcesApi.create(v), [keys.sources])
}
export function useUpdateSource() {
  return useInvalidating(
    (v: { id: number; body: Partial<SourceInput> }) => sourcesApi.update(v.id, v.body),
    [keys.sources, keys.scraps],
  )
}
export function useDeleteSource() {
  return useInvalidating((id: number) => sourcesApi.remove(id), [keys.sources, keys.scraps])
}
export function useReorderSources() {
  return useInvalidating((ids: number[]) => sourcesApi.reorder(ids), [keys.sources])
}

export function useDeleteSession() {
  return useInvalidating((id: number) => authApi.deleteSession(id), [keys.sessions])
}

/** 로그아웃 뒤: 개인 캐시를 비우고 로그인 필요 상태로 둔다 (화면 이동은 호출한 쪽) */
function useSignedOut() {
  const qc = useQueryClient()
  return () => {
    clearPrivateCache(qc)
    qc.setQueryData<ClientAuthStatus>(keys.authStatus, { setup_required: false, logged_in: false })
  }
}

/** 이 기기 로그아웃 */
export function useLogout() {
  const signedOut = useSignedOut()
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      setFlash('로그아웃했어요.')
      signedOut()
    },
  })
}

/** 모든 기기 로그아웃 (현재 기기 포함) → 로그인 화면 */
export function useLogoutAll() {
  const signedOut = useSignedOut()
  return useMutation({
    mutationFn: authApi.logoutAll,
    onSuccess: () => {
      setFlash('모든 기기에서 로그아웃했어요. 다시 로그인해 주세요.')
      signedOut()
    },
  })
}
