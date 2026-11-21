// AI 오류 안내: 하루 사용량 소진(429 + 긴 Retry-After)과 짧은 429의 표시 차이
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/http'
import { AiErrorNotice } from './AiStatus'

afterEach(cleanup)

const DAILY_MSG = '오늘 AI 사용량을 모두 썼어요. 내일 다시 시도해 주세요.'

describe('AiErrorNotice: 하루 사용량 소진', () => {
  it('기다리는 동안: 서버 message만, 다시 시도 버튼·남은 시간 없음', () => {
    render(<AiErrorNotice error={new ApiError(429, 'ai_daily_limit', DAILY_MSG, 5 * 3600)} op="search" onRetry={vi.fn()} />)
    expect(screen.getByText(DAILY_MSG)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
    expect(screen.queryByText(/시간/)).toBeNull()
  })

  it('기다린 시간이 지나면 "이제 다시 시도할 수 있어요"만 덧붙이고 버튼은 여전히 없다', () => {
    const e = new ApiError(429, 'ai_daily_limit', DAILY_MSG, 600)
    e.retryAt = Date.now() - 1000
    render(<AiErrorNotice error={e} op="extract" onRetry={vi.fn()} />)
    expect(screen.getByText(/이제 다시 시도할 수 있어요/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
  })

  it('Retry-After가 짧아도(자정 직전) ai_daily_limit이면 남은 시간·다시 시도 버튼 없음', () => {
    render(<AiErrorNotice error={new ApiError(429, 'ai_daily_limit', DAILY_MSG, 30)} op="search" onRetry={vi.fn()} />)
    expect(screen.getByText(DAILY_MSG)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
    expect(screen.queryByText(/뒤에 다시 시도할 수 있어요/)).toBeNull()
  })

  it('too_many_requests는 Retry-After가 커도 남은 시간과 (막힌) 다시 시도 버튼', () => {
    render(<AiErrorNotice error={new ApiError(429, 'too_many_requests', 'AI 요청이 너무 많아요.', 3600)} op="search" onRetry={vi.fn()} />)
    expect(screen.getByText(/1시간 뒤에 다시 시도할 수 있어요/)).toBeTruthy()
    expect((screen.getByRole('button', { name: '다시 시도' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('짧은 429는 남은 시간과 (막힌) 다시 시도 버튼', () => {
    render(<AiErrorNotice error={new ApiError(429, 'too_many_requests', 'AI 요청이 너무 많아요.', 5)} op="search" onRetry={vi.fn()} />)
    expect(screen.getByText(/5초 뒤에 다시 시도할 수 있어요/)).toBeTruthy()
    expect((screen.getByRole('button', { name: '다시 시도' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
