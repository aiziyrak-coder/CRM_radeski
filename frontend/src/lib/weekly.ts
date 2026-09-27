// A doctor's weekly hours as the settings screen edits them: per day one or more blocks
// (a branch, from–to) with lunch breaks. Stored as plain rows (several rows a day = a break).
import type { ScheduleRowIn } from './scheduling'

export type Break = { start: string; end: string }
export type Block = { branch_id: string; start: string; end: string; breaks: Break[] }
/** index = weekday (0 = Monday) */
export type Week = Block[][]

/** Stored rows -> per-day blocks: rows of one branch on one day form a block, gaps are breaks. */
export function rowsToWeek(rows: ScheduleRowIn[]): Week {
  const week: Week = Array.from({ length: 7 }, () => [])
  const sorted = [...rows].sort((a, b) => a.weekday - b.weekday || a.start_time.localeCompare(b.start_time))
  for (const r of sorted) {
    const start = r.start_time.slice(0, 5)
    const end = r.end_time.slice(0, 5)
    const day = week[r.weekday]
    const block = day.find((b) => b.branch_id === r.branch_id)
    if (block) {
      if (start > block.end) block.breaks.push({ start: block.end, end: start })
      if (end > block.end) block.end = end
    } else {
      day.push({ branch_id: r.branch_id, start, end, breaks: [] })
    }
  }
  return week
}

/** Per-day blocks -> rows: each block minus its breaks. */
export function weekToRows(week: Week): ScheduleRowIn[] {
  const rows: ScheduleRowIn[] = []
  week.forEach((blocks, weekday) => {
    for (const b of blocks) {
      let cursor = b.start
      for (const br of [...b.breaks].sort((x, y) => x.start.localeCompare(y.start))) {
        if (br.start > cursor)
          rows.push({ branch_id: b.branch_id, weekday, start_time: cursor, end_time: br.start })
        if (br.end > cursor) cursor = br.end
      }
      if (cursor < b.end) rows.push({ branch_id: b.branch_id, weekday, start_time: cursor, end_time: b.end })
    }
  })
  return rows
}

/** i18n key of what's wrong with a day's blocks, or null */
export function dayProblem(blocks: Block[]): string | null {
  for (const b of blocks) {
    if (!b.start || !b.end || b.start >= b.end) return 'wsched.errHours'
    const breaks = [...b.breaks].sort((x, y) => x.start.localeCompare(y.start))
    for (const [i, br] of breaks.entries()) {
      if (!br.start || !br.end || br.start >= br.end) return 'wsched.errBreak'
      if (br.start <= b.start || br.end >= b.end) return 'wsched.errBreakOutside'
      if (i > 0 && br.start < breaks[i - 1].end) return 'wsched.errBreakOverlap'
    }
  }
  const spans = [...blocks].sort((x, y) => x.start.localeCompare(y.start))
  for (let i = 1; i < spans.length; i++)
    if (spans[i].start < spans[i - 1].end) return 'wsched.errBlocksOverlap'
  return null
}

/** "Standart grafik": Monday–Saturday 08:00–18:00 at one branch */
export function standardWeek(branchId: string): Week {
  return Array.from({ length: 7 }, (_, d) =>
    d < 6 ? [{ branch_id: branchId, start: '08:00', end: '18:00', breaks: [] }] : [],
  )
}
