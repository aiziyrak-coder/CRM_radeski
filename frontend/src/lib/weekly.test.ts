import { describe, expect, it } from 'vitest'
import { landingFor, navFor } from './navigation'
import { addDays, weekStart, weekdayOf } from './scheduling'
import { dayProblem, rowsToWeek, standardWeek, weekToRows } from './weekly'

const B1 = 'branch-1'
const B2 = 'branch-2'

describe('weekly schedule editor: rows <-> days with breaks', () => {
  it('two rows of one branch on a day are one working day with a lunch break', () => {
    const week = rowsToWeek([
      { branch_id: B1, weekday: 0, start_time: '14:00:00', end_time: '18:00:00' },
      { branch_id: B1, weekday: 0, start_time: '08:00:00', end_time: '13:00:00' },
    ])
    expect(week[0]).toEqual([
      { branch_id: B1, start: '08:00', end: '18:00', breaks: [{ start: '13:00', end: '14:00' }] },
    ])
    expect(week[1]).toEqual([])
  })

  it('a break is saved as two rows, and loading them back gives the same day', () => {
    const week = standardWeek(B1)
    week[2][0].breaks.push({ start: '13:00', end: '14:00' })
    const rows = weekToRows(week)
    expect(rows.filter((r) => r.weekday === 2)).toEqual([
      { branch_id: B1, weekday: 2, start_time: '08:00', end_time: '13:00' },
      { branch_id: B1, weekday: 2, start_time: '14:00', end_time: '18:00' },
    ])
    expect(rows.filter((r) => r.weekday === 6)).toEqual([]) // Sunday off
    expect(rowsToWeek(rows)).toEqual(week)
  })

  it('a day split between two branches stays two blocks', () => {
    const week = rowsToWeek([
      { branch_id: B1, weekday: 4, start_time: '08:00', end_time: '12:00' },
      { branch_id: B2, weekday: 4, start_time: '13:00', end_time: '18:00' },
    ])
    expect(week[4].map((b) => b.branch_id)).toEqual([B1, B2])
    expect(dayProblem(week[4])).toBeNull()
  })

  it('reports impossible hours before they reach the server', () => {
    expect(dayProblem([{ branch_id: B1, start: '18:00', end: '08:00', breaks: [] }])).toBe('wsched.errHours')
    expect(
      dayProblem([
        { branch_id: B1, start: '08:00', end: '18:00', breaks: [{ start: '07:00', end: '09:00' }] },
      ]),
    ).toBe('wsched.errBreakOutside')
    expect(
      dayProblem([
        { branch_id: B1, start: '08:00', end: '13:00', breaks: [] },
        { branch_id: B2, start: '12:00', end: '18:00', breaks: [] },
      ]),
    ).toBe('wsched.errBlocksOverlap')
  })
})

describe('week helpers', () => {
  it('finds the Monday of a week', () => {
    expect(weekdayOf('2026-09-27')).toBe(6) // Sunday
    expect(weekStart('2026-09-27')).toBe('2026-09-21')
    expect(weekStart('2026-09-21')).toBe('2026-09-21')
    expect(addDays('2026-09-21', 6)).toBe('2026-09-27')
  })
})

describe('registrar lands on the schedule (TZ 4.3 "Registrator ekrani")', () => {
  it('the registrar starts on /schedule and has no separate home page', () => {
    expect(landingFor('registrar')).toBe('/schedule')
    expect(navFor('registrar').some((i) => i.path === '/')).toBe(false)
    expect(landingFor('operator')).toBe('/')
  })
})
