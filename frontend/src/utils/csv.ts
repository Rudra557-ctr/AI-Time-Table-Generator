import Papa from 'papaparse'
import type { TimetableRow } from '../api/types'

/** Parses the flat full-timetable CSV (offering_id,course_id,section_id,...)
 * just far enough to list distinct sections — the actual grid for a chosen
 * section comes from /api/download_class, which is already laid out
 * server-side (and correctly accounts for multi-period lab sessions), so we
 * don't duplicate that chaining logic here. */
export function parseSectionIds(csvText: string): string[] {
  const parsed = Papa.parse<TimetableRow>(csvText, { header: true, skipEmptyLines: true })
  const ids = new Set<string>()
  for (const row of parsed.data) {
    if (row.section_id) ids.add(row.section_id)
  }
  return Array.from(ids).sort()
}

export interface DashboardStats {
  sessionCount: number
  sectionCount: number
  facultyUtilizationPct: number
  roomUtilizationPct: number
  todayCount: number
}

const WEEKDAY_CODES = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']

/** Real, computed-from-data KPIs for the Dashboard — not fabricated. Both
 * utilization figures are (distinct entity+slot occupied) / (entity count *
 * total weekly slots), which slightly undercounts multi-period lab sessions
 * (they only appear as one row in the full CSV) — an honest lower bound,
 * not an inflated number. */
export function computeDashboardStats(
  csvText: string,
  facultyCount: number,
  roomCount: number,
  totalWeeklySlots: number,
): DashboardStats {
  const parsed = Papa.parse<TimetableRow>(csvText, { header: true, skipEmptyLines: true })
  const rows = parsed.data.filter((r) => r.slot_id && r.slot_id !== 'UNASSIGNED')
  const sections = new Set<string>()
  const facultySlots = new Set<string>()
  const roomSlots = new Set<string>()
  const todayCode = WEEKDAY_CODES[new Date().getDay()]
  let todayCount = 0
  for (const r of rows) {
    if (r.section_id) sections.add(r.section_id)
    if (r.faculty_id) facultySlots.add(`${r.faculty_id}__${r.slot_id}`)
    if (r.room_id) roomSlots.add(`${r.room_id}__${r.slot_id}`)
    if (r.day === todayCode) todayCount += 1
  }
  const facultyDenom = facultyCount * totalWeeklySlots
  const roomDenom = roomCount * totalWeeklySlots
  return {
    sessionCount: rows.length,
    sectionCount: sections.size,
    facultyUtilizationPct: facultyDenom ? Math.round((facultySlots.size / facultyDenom) * 100) : 0,
    roomUtilizationPct: roomDenom ? Math.round((roomSlots.size / roomDenom) * 100) : 0,
    todayCount,
  }
}

/** ChangedEntry.key is a bare offering_id for "Teacher" changes, or a
 * [offering_id, session_index] tuple for "Start"/"Room" changes — see
 * types.ts. Renders either shape as one readable label. */
export function formatChangedKey(key: string | [string, number]): string {
  if (Array.isArray(key)) {
    const [offeringId, sessionIdx] = key
    return `${offeringId} · session ${sessionIdx + 1}`
  }
  return key
}

export function todayDayCode(): string {
  return WEEKDAY_CODES[new Date().getDay()]
}

export interface ClassGrid {
  periodHeaders: string[]
  /** Parallel to periodHeaders — true for a synthetic lunch column inserted
   * where the backend's fixed period list has a time gap (see below). */
  isLunchColumn: boolean[]
  rows: { day: string; cells: string[] }[]
}

const LUNCH_LABEL = 'Lunch Break'

/** backend/app.py:_write_class_grids bakes a FIXED period-header list —
 * "09:00-10:00", ..., "12:00-13:00", "14:00-15:00", ... — with no column at
 * all for the 13:00-14:00 gap between them. Left as-is, the grid just jumps
 * straight from 12:00-13:00 to 14:00-15:00 with nothing marking why. This
 * scans consecutive "HH:MM-HH:MM" headers for exactly that kind of gap and
 * inserts a synthetic "Lunch Break" column so the break is shown explicitly
 * instead of silently disappearing. */
function parseHm(t: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(t.trim())
  if (!m) return null
  return Number(m[1]) * 60 + Number(m[2])
}

function withLunchColumns(periodHeaders: string[], rows: { day: string; cells: string[] }[]): ClassGrid {
  const outHeaders: string[] = []
  const isLunchColumn: boolean[] = []
  let gapsFound = 0
  for (let i = 0; i < periodHeaders.length; i++) {
    outHeaders.push(periodHeaders[i])
    isLunchColumn.push(false)
    if (i < periodHeaders.length - 1) {
      const endStr = periodHeaders[i].split('-')[1] || ''
      const nextStartStr = periodHeaders[i + 1].split('-')[0] || ''
      const end = parseHm(endStr)
      const nextStart = parseHm(nextStartStr)
      if (end !== null && nextStart !== null && end !== nextStart) {
        outHeaders.push(`${endStr.trim()}-${nextStartStr.trim()}`)
        isLunchColumn.push(true)
        gapsFound++
      }
    }
  }
  if (gapsFound === 0) return { periodHeaders, isLunchColumn: periodHeaders.map(() => false), rows }
  const outRows = rows.map((r) => {
    const cells: string[] = []
    let src = 0
    for (const isLunch of isLunchColumn) {
      cells.push(isLunch ? LUNCH_LABEL : r.cells[src++])
    }
    return { day: r.day, cells }
  })
  return { periodHeaders: outHeaders, isLunchColumn, rows: outRows }
}

/** Parses a class_timetables/{section}.csv (header: "Day/Period" + period
 * time ranges; one row per weekday; cell = "COURSECODE ROOM FACULTY" or an
 * em dash) into a renderable grid — this file is written by
 * backend/app.py:_write_timetable_and_grids, so the shape is fixed. */
export function parseClassGridCsv(csvText: string): ClassGrid {
  const parsed = Papa.parse<string[]>(csvText, { skipEmptyLines: true })
  const [header, ...rest] = parsed.data as string[][]
  const periodHeaders = (header || []).slice(1)
  const rows = rest
    .filter((r) => r && r.length > 0)
    .map((r) => ({ day: r[0], cells: r.slice(1) }))
  return withLunchColumns(periodHeaders, rows)
}
