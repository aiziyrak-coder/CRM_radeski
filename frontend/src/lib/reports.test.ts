import { describe, expect, it } from 'vitest'
import { delta, periodRange } from './reports'

describe('periodRange', () => {
  it('counts today in the period', () => {
    expect(periodRange('today', '2026-09-27')).toEqual({ from: '2026-09-27', to: '2026-09-27' })
    expect(periodRange('7d', '2026-09-27')).toEqual({ from: '2026-09-21', to: '2026-09-27' })
    expect(periodRange('30d', '2026-03-01')).toEqual({ from: '2026-01-31', to: '2026-03-01' })
  })
})

describe('delta', () => {
  it('knows which way is better', () => {
    expect(delta('dial_rate', 60, 50)).toEqual({ diff: 10, tone: 'good' })
    expect(delta('no_show_rate', 12.5, 10)).toEqual({ diff: 2.5, tone: 'bad' })
    expect(delta('first_response_median_min', 8, 12)).toEqual({ diff: -4, tone: 'good' })
    expect(delta('qa_score', 70, 70)).toEqual({ diff: 0, tone: 'flat' })
  })

  it('has nothing to say without both values', () => {
    expect(delta('dial_rate', null, 50)).toBeNull()
    expect(delta('dial_rate', 50, null)).toBeNull()
    expect(delta('dial_rate', 50, undefined)).toBeNull()
  })
})
