import type { TFunction } from 'i18next'
import { formatDateTime } from './patients'
import { clinicDate } from './scheduling'

const DAY = 86_400_000

/** Whole days between two clinic dates ('YYYY-MM-DD'): positive = `day` is in the future. */
export function daysFromToday(day: string, today: string = clinicDate()): number {
  return Math.round((Date.parse(`${day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / DAY)
}

/** Clinic-time HH:MM of a timestamp. */
export function clinicTime(iso: string): string {
  return formatDateTime(iso).slice(-5)
}

/**
 * "bugun 14:30", "ertaga 09:00", "kecha 18:10", "3 kun oldin", "5 kundan keyin", or the date.
 * Pair it with `title={formatDateTime(iso)}` so the exact moment is one hover away.
 */
export function relativeDay(t: TFunction, iso: string | null, now: Date = new Date()): string {
  if (!iso) return '—'
  const day = clinicDate(iso)
  const diff = daysFromToday(day, clinicDate(now))
  const time = clinicTime(iso)
  if (diff === 0) return t('time.todayAt', { time })
  if (diff === 1) return t('time.tomorrowAt', { time })
  if (diff === -1) return t('time.yesterdayAt', { time })
  if (diff < 0 && diff >= -30) return t('time.daysAgo', { count: -diff })
  if (diff > 0 && diff <= 30) return t('time.inDays', { count: diff })
  return formatDateTime(iso).slice(0, 10)
}

/** "5 daq", "2 soat 10 daq", "3 kun" — for waits, durations since, SLA countdowns. */
export function humanMinutes(t: TFunction, minutes: number): string {
  const m = Math.max(0, Math.round(minutes))
  if (m < 60) return t('time.minutes', { count: m })
  if (m < 60 * 24) {
    const h = Math.floor(m / 60)
    const rest = m % 60
    return rest ? t('time.hoursMinutes', { h, m: rest }) : t('time.hours', { count: h })
  }
  return t('time.days', { count: Math.floor(m / 1440) })
}
