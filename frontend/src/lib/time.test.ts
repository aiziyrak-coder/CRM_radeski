import type { TFunction } from 'i18next'
import { describe, expect, it } from 'vitest'
import { daysFromToday, humanMinutes, relativeDay } from './time'

// echoes the key and its options so the logic is tested without the translation files
const t = ((key: string, o?: Record<string, unknown>) =>
  o ? `${key}:${JSON.stringify(o)}` : key) as unknown as TFunction

describe('relative days in clinic time (UTC+5)', () => {
  const now = new Date('2026-09-27T07:00:00Z') // 12:00 in Tashkent
  it('today / tomorrow / yesterday with the clinic time', () => {
    expect(relativeDay(t, '2026-09-27T09:30:00Z', now)).toBe('time.todayAt:{"time":"14:30"}')
    expect(relativeDay(t, '2026-09-27T20:00:00Z', now)).toBe('time.tomorrowAt:{"time":"01:00"}')
    expect(relativeDay(t, '2026-09-26T13:10:00Z', now)).toBe('time.yesterdayAt:{"time":"18:10"}')
  })
  it('days ago / in days, then the plain date', () => {
    expect(relativeDay(t, '2026-09-24T07:00:00Z', now)).toBe('time.daysAgo:{"count":3}')
    expect(relativeDay(t, '2026-10-02T07:00:00Z', now)).toBe('time.inDays:{"count":5}')
    expect(relativeDay(t, '2026-01-02T07:00:00Z', now)).toBe('02.01.2026')
    expect(relativeDay(t, null, now)).toBe('—')
  })
  it('counts whole clinic days', () => {
    expect(daysFromToday('2026-09-30', '2026-09-27')).toBe(3)
  })
})

describe('durations', () => {
  it('minutes, hours, days', () => {
    expect(humanMinutes(t, 5)).toBe('time.minutes:{"count":5}')
    expect(humanMinutes(t, 130)).toBe('time.hoursMinutes:{"h":2,"m":10}')
    expect(humanMinutes(t, 120)).toBe('time.hours:{"count":2}')
    expect(humanMinutes(t, 3000)).toBe('time.days:{"count":2}')
  })
})
