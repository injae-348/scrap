// 목 데이터. 모두 가짜 URL·가짜 제목이다. (실제 스크랩 내용 아님)
// 마감일은 오늘 기준 상대값으로 만들어 언제 열어도 지남/임박/먼 것/없음이 섞이게 한다.

import type { Scrap, Session, Source, Topic } from '../api/types'
import { addDaysISO } from '../lib/date'

export const initialSources: Source[] = [
  { id: 1, name: '유튜브', domain_patterns: ['youtube.com', 'youtu.be'], is_default: false },
  { id: 2, name: 'X', domain_patterns: ['x.com', 'twitter.com'], is_default: false },
  // 패턴에 맞는 출처가 없을 때 쓰는 기본 출처
  { id: 3, name: '일반사이트', domain_patterns: [], is_default: true },
  { id: 4, name: '당근', domain_patterns: ['daangn.com'], is_default: false },
  { id: 5, name: '커뮤니티', domain_patterns: ['community.example.com', 'forum.example.org'], is_default: false },
  { id: 6, name: '깃허브', domain_patterns: ['github.com'], is_default: false },
]

export const initialTopics: Topic[] = [
  { id: 1, name: 'claude' },
  { id: 2, name: 'security' },
  { id: 3, name: 'docker' },
  { id: 4, name: '공모전' },
  { id: 5, name: 'react' },
  { id: 6, name: '디자인' },
  { id: 7, name: '요리' },
  { id: 8, name: '중고거래' },
]

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * 3_600_000).toISOString()
}

interface Seed {
  url: string
  title: string
  memo?: string
  source: number
  topics: number[]
  liked?: boolean
  due?: number | null
  ago: number
}

const seeds: Seed[] = [
  {
    url: 'https://www.youtube.com/watch?v=MOCK0000001',
    title: '[가상 영상] Claude로 30분 만에 사이드 프로젝트 만들기',
    memo: '## 요약\n- 기획 → 프롬프트 → 코드 리뷰 순서로 진행\n- **서브에이전트**로 역할 분리\n\n> 작은 단위로 자주 확인하는 게 핵심',
    source: 1,
    topics: [1],
    liked: true,
    ago: 2,
  },
  {
    url: 'https://contest.example.com/2026/ai-idea',
    title: '[가상] 2026 AI 아이디어 공모전 참가 안내',
    memo: '접수 마감 전에 **기획서 PDF** 제출 필요.\n\n1. 팀 구성 (최대 3명)\n2. 기획서 5쪽 이내\n3. 시연 영상 선택',
    source: 3,
    topics: [4, 1],
    liked: true,
    due: 3,
    ago: 5,
  },
  {
    url: 'https://x.com/example/status/1000000000000000001',
    title: '[가상 게시물] 도커 이미지 용량 줄이는 팁 모음',
    memo: '- 멀티 스테이지 빌드\n- `.dockerignore` 꼭 쓰기\n- slim 베이스 이미지',
    source: 2,
    topics: [3],
    ago: 9,
  },
  {
    url: 'https://www.daangn.com/articles/mock-0001',
    title: '[가상 매물] 원목 책상 1200 사이즈 나눔',
    memo: '토요일 오후 직거래 가능하다고 함.',
    source: 4,
    topics: [8],
    liked: false,
    due: 0,
    ago: 20,
  },
  {
    url: 'https://blog.example.com/posts/secure-cookie',
    title: '[가상 글] HttpOnly · SameSite 쿠키 정리',
    memo: '### 핵심\n| 속성 | 의미 |\n|---|---|\n| HttpOnly | JS 접근 차단 |\n| Secure | HTTPS만 |\n| SameSite | 교차 사이트 요청 제한 |',
    source: 3,
    topics: [2],
    liked: true,
    ago: 30,
  },
  {
    url: 'https://community.example.com/threads/mock-42',
    title: '[가상 스레드] 홈서버 1GB 램으로 버티는 법',
    memo: '스왑 2GB 설정 + 컨테이너 메모리 제한.\n\n<b>HTML 태그는 굵게 보이지 않고 그대로 무시되어야 합니다</b>\n\n<script>alert("xss")</script>\n\n[위험한 링크](javascript:alert(1))',
    source: 5,
    topics: [3, 2],
    ago: 48,
  },
  {
    url: 'https://github.com/example-org/example-repo',
    title: '[가상 저장소] example-repo: 미니멀 마크다운 에디터',
    source: 6,
    topics: [5, 6],
    ago: 52,
  },
  {
    url: 'https://youtu.be/MOCK0000002',
    title: '[가상 영상] 10분 집밥: 계란 간장 덮밥',
    memo: '재료: 계란 2, 간장 1큰술, 버터 조금, 쪽파',
    source: 1,
    topics: [7],
    liked: true,
    ago: 70,
  },
  {
    url: 'https://design.example.org/award-2026',
    title: '[가상] 학생 UI 디자인 어워드 작품 접수',
    memo: '포트폴리오 링크 + 작품 설명 300자',
    source: 3,
    topics: [4, 6],
    due: 6,
    ago: 80,
  },
  {
    url: 'https://x.com/example/status/1000000000000000002',
    title: '[가상 게시물] React 19 폼 액션 짧은 예제',
    source: 2,
    topics: [5],
    ago: 96,
  },
  {
    url: 'https://hackathon.example.com/winter',
    title: '[가상] 겨울 해커톤 사전 등록',
    memo: '사전 등록 마감이 지남. 다음 회차 알림 신청만 해두기.',
    source: 3,
    topics: [4],
    due: -4,
    ago: 120,
  },
  {
    url: 'https://www.youtube.com/watch?v=MOCK0000003',
    title: '[가상 영상] 보안 입문: 비밀번호 해시와 Argon2',
    source: 1,
    topics: [2],
    ago: 140,
  },
  {
    url: 'https://www.daangn.com/articles/mock-0002',
    title: '[가상 매물] 기계식 키보드 저소음 적축',
    memo: '가격 제안 가능 여부 물어보기',
    source: 4,
    topics: [8],
    due: -1,
    ago: 160,
  },
  {
    url: 'https://docs.example.com/compose/healthcheck',
    title: '[가상 문서] Compose 헬스체크와 재시작 정책',
    memo: '```yaml\nhealthcheck:\n  test: ["CMD", "curl", "-f", "http://localhost/health"]\n  interval: 30s\n```',
    source: 3,
    topics: [3],
    liked: true,
    ago: 200,
  },
  {
    url: 'https://forum.example.org/t/mock-7',
    title: '[가상 글] 개인 북마크 정리 방법 공유',
    source: 5,
    topics: [6],
    ago: 260,
  },
  {
    url: 'https://grant.example.com/creator-fund',
    title: '[가상] 1인 개발자 지원금 2차 모집',
    memo: '사업계획서 양식 다운로드 후 작성.',
    source: 3,
    topics: [4],
    due: 21,
    ago: 300,
  },
  {
    url: 'https://github.com/example-org/mock-cli',
    title: '[가상 저장소] mock-cli: 터미널 TODO 도구',
    source: 6,
    topics: [5],
    ago: 340,
  },
  {
    url: 'https://www.youtube.com/watch?v=MOCK0000004',
    title: '[가상 영상] Claude API 도구 호출 따라하기',
    memo: '도구 호출 루프: 요청 → tool_use → 결과 전달 → 최종 답변',
    source: 1,
    topics: [1],
    due: 45,
    ago: 400,
  },
  {
    url: 'https://recipe.example.com/kimchi-stew',
    title: '[가상 레시피] 참치 김치찌개',
    source: 3,
    topics: [7],
    ago: 500,
  },
  {
    url: 'https://community.example.com/threads/mock-99',
    title: '[가상 스레드] TOTP 복구 코드 보관 어떻게 하세요?',
    memo: '오프라인 종이 + 비밀번호 관리자 두 군데.',
    source: 5,
    topics: [2],
    liked: true,
    ago: 600,
  },
  {
    url: 'https://example.com/untitled',
    title: '[가상] 주제 없는 메모용 링크',
    source: 3,
    topics: [],
    ago: 720,
  },
]

export function buildInitialScraps(): Scrap[] {
  return seeds.map((s, i) => {
    const created = hoursAgo(s.ago)
    const src = initialSources.find((x) => x.id === s.source)!
    return {
      id: i + 1,
      url: s.url,
      title: s.title,
      memo: s.memo ?? '',
      source: { id: src.id, name: src.name },
      topics: s.topics.map((tid) => initialTopics.find((t) => t.id === tid)!),
      liked: s.liked ?? false,
      due_date: s.due === undefined || s.due === null ? null : addDaysISO(s.due),
      created_at: created,
      updated_at: created,
    }
  })
}

export const initialSessions: Session[] = [
  {
    id: 1,
    user_agent: 'Safari · iPhone (홈 화면 앱)',
    created_at: hoursAgo(24 * 30),
    last_seen_at: hoursAgo(0.1),
    current: false,
  },
  {
    id: 2,
    user_agent: 'Chrome · macOS',
    created_at: hoursAgo(24 * 3),
    last_seen_at: hoursAgo(0),
    current: true,
  },
  {
    id: 3,
    user_agent: 'Firefox · Windows',
    created_at: hoursAgo(24 * 60),
    last_seen_at: hoursAgo(24 * 12),
    current: false,
  },
]
