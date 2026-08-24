import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import Papa from 'papaparse'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { EmptyState } from '../components/common/EmptyState'
import { DataTable } from '../components/common/DataTable'
import { ProgressBar } from '../components/common/ProgressBar'
import { ScheduleGrid } from '../components/common/ScheduleGrid'
import { Icon } from '../components/common/Icon'
import { getDatasetRows, fetchTimetableCsvText } from '../api/endpoints'
import type { IconName } from '../components/common/Icon'
import type { TimetableRow } from '../api/types'
import type { ClassGrid } from '../utils/csv'
import { computeFacultyWorkload } from '../utils/workload'
import styles from './ResourceListPage.module.css'

const ICONS: Record<string, IconName> = { sections: 'users', faculty: 'cap', rooms: 'door', courses: 'book' }

const COURSE_TYPE_TONE: Record<string, string> = { LAB: 'badgeOk', WORKSHOP: 'badgeWarn' }

const DAY_ORDER = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

/** Builds a day x period occupancy grid for one faculty member or one room,
 * entirely client-side from the already-generated full timetable — no new
 * backend endpoint needed. Period columns come from every distinct
 * start/end time in the WHOLE schedule (not just this entity's own slots),
 * so empty periods still show as "—" instead of collapsing the grid. */
function buildOccupancyGrid(rows: TimetableRow[], key: 'faculty_id' | 'room_id', value: string, courseCode: Map<string, string>): ClassGrid {
  const scheduled = rows.filter((r) => r.slot_id && r.slot_id !== 'UNASSIGNED')
  const periodMap = new Map<string, string>()
  for (const r of scheduled) {
    const pk = `${r.start_time}|${r.end_time}`
    if (!periodMap.has(pk)) periodMap.set(pk, `${r.start_time}-${r.end_time}`)
  }
  const periodKeys = Array.from(periodMap.keys()).sort((a, b) => a.localeCompare(b))
  const periodHeaders = periodKeys.map((pk) => periodMap.get(pk) as string)

  const days = Array.from(new Set(scheduled.map((r) => r.day))).sort(
    (a, b) => DAY_ORDER.indexOf(a) - DAY_ORDER.indexOf(b),
  )

  const otherKey = key === 'faculty_id' ? 'room_id' : 'faculty_id'
  const rowsOut = days.map((day) => ({
    day,
    cells: periodKeys.map((pk) => {
      const match = scheduled.find((r) => r.day === day && `${r.start_time}|${r.end_time}` === pk && r[key] === value)
      if (!match) return '—'
      const code = courseCode.get(match.course_id) ?? match.course_id
      return `${code}\n${match.section_id} · ${match[otherKey]}`
    }),
  }))

  return { periodHeaders, rows: rowsOut }
}

function useOccupancy(jobId: string | null, hasSolved: boolean) {
  const [fullRows, setFullRows] = useState<TimetableRow[] | null>(null)
  const [courseCode, setCourseCode] = useState<Map<string, string>>(new Map())
  const [loadingOccupancy, setLoadingOccupancy] = useState(false)
  const [occupancyError, setOccupancyError] = useState<string | null>(null)

  async function ensureLoaded() {
    if (!jobId || !hasSolved || fullRows) return
    setLoadingOccupancy(true)
    setOccupancyError(null)
    try {
      const [csvText, coursesRes] = await Promise.all([fetchTimetableCsvText(jobId), getDatasetRows(jobId, 'courses')])
      const parsed = Papa.parse<TimetableRow>(csvText, { header: true, skipEmptyLines: true })
      setFullRows(parsed.data)
      setCourseCode(new Map(coursesRes.rows.map((c) => [c.course_id, c.course_code])))
    } catch {
      setOccupancyError('Could not load the generated schedule for occupancy.')
    } finally {
      setLoadingOccupancy(false)
    }
  }

  return { fullRows, courseCode, loadingOccupancy, occupancyError, ensureLoaded }
}

function SectionsGrid({ rows, onOpen }: { rows: Record<string, string>[]; onOpen: (sectionId: string) => void }) {
  return (
    <div className={styles.cardGrid}>
      {rows.map((r) => (
        <button key={r.section_id} className={styles.tileButton} onClick={() => onOpen(r.section_id)}>
          <div className={styles.tileHead}>
            <span className={styles.tileTitle}>{r.section_id}</span>
            <span className={styles.badge}>Year {r.year}</span>
          </div>
          <div className={styles.tileMeta}>
            <span className={`${styles.badge} ${styles.badgeAccent}`}>{r.program_id}</span>
            <span className={styles.tileSub}>{r.student_count} students</span>
          </div>
          <div className={styles.tileHint}>View timetable →</div>
        </button>
      ))}
    </div>
  )
}

function CoursesGrid({ rows }: { rows: Record<string, string>[] }) {
  return (
    <div className={styles.cardGrid}>
      {rows.map((r) => (
        <div key={r.course_id} className={styles.tile}>
          <div className={styles.tileHead}>
            <span className={styles.tileTitle}>{r.course_code}</span>
            <span className={`${styles.badge} ${styles[COURSE_TYPE_TONE[r.course_type] ?? ''] ?? ''}`}>{r.course_type}</span>
          </div>
          <div className={styles.tileName}>{r.course_name}</div>
          <div className={styles.tileSub}>
            {r.credits} cr · {r.sessions_per_week}x/wk · {r.session_duration}h
          </div>
          <div className={styles.tileDivider} />
          <div className={styles.tileMeta}>
            <span className={styles.badge}>{r.course_category}</span>
            <span className={styles.badge}>{r.required_room_type}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function OccupancyPanel({
  occupancy,
  entityKey,
  entityValue,
  entityLabel,
}: {
  occupancy: ReturnType<typeof useOccupancy>
  entityKey: 'faculty_id' | 'room_id'
  entityValue: string
  entityLabel: string
}) {
  if (occupancy.loadingOccupancy) return <div className={styles.occupancyLoading}>Loading occupancy…</div>
  if (occupancy.occupancyError) return <div className={styles.occupancyLoading}>{occupancy.occupancyError}</div>
  if (!occupancy.fullRows) return null
  const grid = buildOccupancyGrid(occupancy.fullRows, entityKey, entityValue, occupancy.courseCode)
  return (
    <div className={styles.occupancyPanel}>
      <div className={styles.occupancyTitle}>{entityLabel} — weekly occupancy</div>
      <ScheduleGrid grid={grid} />
    </div>
  )
}

function FacultyList({
  rows,
  hasSolved,
  occupancy,
  expanded,
  onToggle,
}: {
  rows: Record<string, string>[]
  hasSolved: boolean
  occupancy: ReturnType<typeof useOccupancy>
  expanded: string | null
  onToggle: (id: string) => void
}) {
  const workloadById = new Map(
    occupancy.fullRows ? computeFacultyWorkload(occupancy.fullRows, rows).map((w) => [w.faculty_id, w]) : [],
  )

  return (
    <ul className={styles.entityList}>
      {rows.map((r) => {
        const max = Number(r.max_hours_per_week) || 0
        const workload = workloadById.get(r.faculty_id)
        const isOpen = expanded === r.faculty_id
        return (
          <li key={r.faculty_id} className={styles.entityRow}>
            <button
              className={styles.entityButton}
              onClick={() => onToggle(r.faculty_id)}
              disabled={!hasSolved}
              title={hasSolved ? 'View occupancy' : 'Generate a schedule first'}
            >
              <div className={styles.entityHead}>
                <span className={styles.entityName}>{r.name}</span>
                {hasSolved && <Icon name={isOpen ? 'grid' : 'calendar'} size={14} />}
              </div>
              <div className={styles.entitySub}>
                {r.faculty_id} · {r.designation}
              </div>
              <div className={styles.entityBarRow}>
                <div className={styles.entityBar}>
                  <ProgressBar value={workload ? Math.min(workload.pct, 100) : 0} tone={workload && workload.pct > 100 ? 'warn' : 'accent'} />
                </div>
                <span className={`${styles.entityBarLabel} mono`}>
                  {workload ? `${workload.assignedHours}/${max}h` : `—/${max}h`}
                </span>
              </div>
            </button>
            {isOpen && (
              <OccupancyPanel occupancy={occupancy} entityKey="faculty_id" entityValue={r.faculty_id} entityLabel={r.name} />
            )}
          </li>
        )
      })}
    </ul>
  )
}

function RoomsList({
  rows,
  hasSolved,
  occupancy,
  expanded,
  onToggle,
}: {
  rows: Record<string, string>[]
  hasSolved: boolean
  occupancy: ReturnType<typeof useOccupancy>
  expanded: string | null
  onToggle: (id: string) => void
}) {
  return (
    <ul className={styles.entityList}>
      {rows.map((r) => {
        const isOpen = expanded === r.room_id
        return (
          <li key={r.room_id} className={styles.entityRow}>
            <button
              className={styles.entityButton}
              onClick={() => onToggle(r.room_id)}
              disabled={!hasSolved}
              title={hasSolved ? 'View occupancy' : 'Generate a schedule first'}
            >
              <div className={styles.entityHead}>
                <span className={styles.entityName}>{r.room_name}</span>
                {hasSolved && <Icon name={isOpen ? 'grid' : 'calendar'} size={14} />}
              </div>
              <div className={styles.entitySub}>
                {r.room_id} · {r.room_type} · cap {r.capacity}
              </div>
            </button>
            {isOpen && (
              <OccupancyPanel occupancy={occupancy} entityKey="room_id" entityValue={r.room_id} entityLabel={r.room_name} />
            )}
          </li>
        )
      })}
    </ul>
  )
}

export function ResourceListPage({ dataset, title }: { dataset: string; title: string }) {
  const { jobId, hasSolved } = useJob()
  const navigate = useNavigate()
  const [rows, setRows] = useState<Record<string, string>[] | null>(null)
  const [columns, setColumns] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const occupancy = useOccupancy(jobId, hasSolved)

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    setError(null)
    setSearch('')
    setExpanded(null)
    getDatasetRows(jobId, dataset)
      .then((res) => {
        setRows(res.rows)
        setColumns(res.rows.length > 0 ? Object.keys(res.rows[0]) : [])
      })
      .catch(() => setError(`${dataset}.csv wasn't found in this upload.`))
      .finally(() => setLoading(false))
  }, [jobId, dataset])

  useEffect(() => {
    // Faculty workload bars are shown for every row immediately (not gated
    // behind a click, unlike the occupancy grid), so this dataset needs the
    // full timetable loaded eagerly rather than waiting for a row expand.
    if (dataset === 'faculty' && hasSolved) occupancy.ensureLoaded()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset, hasSolved, jobId])

  function toggleExpanded(id: string) {
    const next = expanded === id ? null : id
    setExpanded(next)
    if (next) occupancy.ensureLoaded()
  }

  const query = search.trim().toLowerCase()
  const filteredRows = query
    ? (rows ?? []).filter((row) => Object.values(row).some((v) => v.toLowerCase().includes(query)))
    : rows

  if (!jobId) {
    return (
      <>
        <PageHeader title={title} subtitle={`Real ${dataset} data from your uploaded dataset — read-only.`} />
        <Card>
          <EmptyState
            icon={ICONS[dataset] ?? 'grid'}
            title="No dataset loaded yet"
            description="Upload your data to see this list."
            action={<Button onClick={() => navigate('/upload')}>Upload data →</Button>}
          />
        </Card>
      </>
    )
  }

  let body: ReactNode = <DataTable columns={columns} rows={filteredRows ?? []} />
  if (filteredRows && filteredRows.length > 0) {
    if (dataset === 'sections') body = <SectionsGrid rows={filteredRows} onOpen={(id) => navigate(`/timetable?section=${encodeURIComponent(id)}`)} />
    else if (dataset === 'courses') body = <CoursesGrid rows={filteredRows} />
    else if (dataset === 'faculty')
      body = <FacultyList rows={filteredRows} hasSolved={hasSolved} occupancy={occupancy} expanded={expanded} onToggle={toggleExpanded} />
    else if (dataset === 'rooms')
      body = <RoomsList rows={filteredRows} hasSolved={hasSolved} occupancy={occupancy} expanded={expanded} onToggle={toggleExpanded} />
  }

  return (
    <>
      <PageHeader
        title={title}
        subtitle={`${rows ? rows.length : '…'} rows from ${dataset}.csv, as ingested — read-only.`}
      />
      {(dataset === 'faculty' || dataset === 'rooms') && !hasSolved && rows && rows.length > 0 && (
        <div className={styles.occupancyHint}>Generate a schedule first to view occupancy for any {dataset === 'faculty' ? 'faculty member' : 'room'}.</div>
      )}
      {rows && rows.length > 0 && (
        <input
          className={styles.search}
          type="text"
          placeholder={`Search ${dataset}…`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      )}
      {loading && <div className={styles.loading}>Loading…</div>}
      {error && (
        <Card>
          <EmptyState
            icon={ICONS[dataset] ?? 'grid'}
            title={`No ${dataset}.csv in this dataset`}
            description="This file wasn't part of the last upload for this job."
          />
        </Card>
      )}
      {filteredRows && filteredRows.length > 0 && body}
      {rows && rows.length > 0 && filteredRows && filteredRows.length === 0 && (
        <Card>
          <EmptyState icon={ICONS[dataset] ?? 'grid'} title="No matches" description={`No rows match "${search}".`} />
        </Card>
      )}
      {rows && rows.length === 0 && (
        <Card>
          <EmptyState icon={ICONS[dataset] ?? 'grid'} title="Empty" description={`${dataset}.csv has no rows.`} />
        </Card>
      )}
    </>
  )
}
