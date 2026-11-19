import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query'
import { authApi, scrapsApi, sourcesApi, topicsApi } from '../api'
import { ApiError, errorMessage } from '../api/http'
import type { Scrap, ScrapInput, ScrapListParams, ScrapListResponse, ScrapPatch, SourceInput } from '../api/types'
import { showToast } from '../lib/toast'

export const keys = {
  authStatus: ['auth', 'status'] as const,
  sessions: ['auth', 'sessions'] as const,
  scraps: ['scraps'] as const,
  scrapList: (p: ScrapListParams) => ['scraps', 'list', p] as const,
  scrap: (id: number) => ['scraps', 'detail', id] as const,
  sources: ['sources'] as const,
  topics: ['topics'] as const,
}

export const PAGE_SIZE = 15

export function useAuthStatus() {
  return useQuery({ queryKey: keys.authStatus, queryFn: authApi.status, staleTime: 60_000 })
}

export function useScrapList(p: Omit<ScrapListParams, 'cursor' | 'limit'>) {
  return useInfiniteQuery({
    queryKey: keys.scrapList(p),
    queryFn: ({ pageParam }) => scrapsApi.list({ ...p, cursor: pageParam ?? undefined, limit: PAGE_SIZE }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
}

export function useScrap(id: number) {
  return useQuery({ queryKey: keys.scrap(id), queryFn: () => scrapsApi.get(id), enabled: Number.isFinite(id) })
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
    // 생성은 POST(liked 선택), 수정은 PATCH(liked는 보내지 않음 — 좋아요는 PUT /like로만)
    mutationFn: (v: { id: number; body: ScrapPatch } | { id?: undefined; body: ScrapInput }) =>
      v.id !== undefined ? scrapsApi.update(v.id, v.body) : scrapsApi.create(v.body),
    onSuccess: (saved) => {
      qc.setQueryData(keys.scrap(saved.id), saved)
      return qc.invalidateQueries({ queryKey: ['scraps', 'list'] })
    },
  })
}

export function useDeleteScrap() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => scrapsApi.remove(id),
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: keys.scrap(id) })
      return qc.invalidateQueries({ queryKey: ['scraps', 'list'] })
    },
  })
}

/** 좋아요 — 화면은 즉시 바꾸고(낙관적 업데이트), 실패하면 되돌리고 짧게 안내한다 */
export function useToggleLike() {
  const qc = useQueryClient()
  const patch = (id: number, liked: boolean) => {
    qc.setQueriesData<InfiniteData<ScrapListResponse>>({ queryKey: ['scraps', 'list'] }, (old) =>
      old
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
    mutationFn: (s: Pick<Scrap, 'id' | 'liked'>) => scrapsApi.setLike(s.id, !s.liked),
    onMutate: (s) => patch(s.id, !s.liked),
    onError: (e, s) => {
      patch(s.id, s.liked)
      const net = e instanceof ApiError && e.status === 0
      showToast(net ? errorMessage(e) : '좋아요를 바꾸지 못했어요. 잠시 후 다시 시도해 주세요.', 'danger')
    },
    onSuccess: (res, s) => patch(s.id, res.liked),
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
  return useInvalidating((ids: number[]) => topicsApi.reorder(ids), [keys.topics])
}

export function useCreateSource() {
  return useInvalidating(
    (v: SourceInput) => sourcesApi.create(v),
    [keys.sources],
  )
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
export function useLogoutAll() {
  return useInvalidating(() => authApi.logoutAll(), [keys.sessions])
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      // 로그아웃 시 캐시된 개인 데이터를 모두 비운다
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
      return qc.invalidateQueries({ queryKey: keys.authStatus })
    },
  })
}
