import type { TimetableRow } from '../api/types'

export interface FacultyWorkload {
  faculty_id: string
  name: string
  designation: string
  assignedHours: number
  maxHours: number
  pct: number
}

function hoursBetween(start: string, end: string): number {
  const [sh, sm] = start.split(':').map(Number)
  const [eh, em] = end.split(':').map(Number)
  if ([sh, sm, eh, em].some((n) => Number.isNaN(n))) return 0
  return Math.max(0, (eh * 60 + em - (sh * 60 + sm)) / 60)
}

/** Real assigned hours per faculty member, computed from the generated
 * timetable itself (session duration = end_time - start_time, summed per
 * faculty_id) — not a placeholder. Compared against max_hours_per_week from
 * faculty.csv. Shared by ResourceListPage's Faculty list and Analytics'
 * workload section so the two views can never drift apart. */
export function computeFacultyWorkload(
  timetableRows: TimetableRow[],
  facultyRows: Record<string, string>[],
): FacultyWorkload[] {
  const hoursByFaculty = new Map<string, number>()
  for (const r of timetableRows) {
    if (!r.slot_id || r.slot_id === 'UNASSIGNED' || !r.faculty_id) continue
    const prev = hoursByFaculty.get(r.faculty_id) ?? 0
    hoursByFaculty.set(r.faculty_id, prev + hoursBetween(r.start_time, r.end_time))
  }

  return facultyRows.map((f) => {
    const assignedHours = hoursByFaculty.get(f.faculty_id) ?? 0
    const maxHours = Number(f.max_hours_per_week) || 0
    const pct = maxHours > 0 ? Math.round((assignedHours / maxHours) * 100) : 0
    return {
      faculty_id: f.faculty_id,
      name: f.name,
      designation: f.designation,
      assignedHours: Math.round(assignedHours * 10) / 10,
      maxHours,
      pct,
    }
  })
}
