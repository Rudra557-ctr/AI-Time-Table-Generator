import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { Banner } from '../components/common/Banner'
import { EmptyState } from '../components/common/EmptyState'
import { BarChart } from '../components/common/BarChart'
import { getDatasetRows } from '../api/endpoints'
import styles from './ElectivesPage.module.css'

interface ElectiveGroupView {
  id: string
  name: string
  type: string
  year: string
  courses: string[]
  byProgram: { label: string; value: number }[]
  total: number
}

async function loadElectiveGroups(jobId: string): Promise<ElectiveGroupView[]> {
  const [groups, groupCourses, enrollments, students, programs, courses] = await Promise.all([
    getDatasetRows(jobId, 'elective_groups'),
    getDatasetRows(jobId, 'elective_group_courses'),
    getDatasetRows(jobId, 'student_enrollments'),
    getDatasetRows(jobId, 'students'),
    getDatasetRows(jobId, 'programs'),
    getDatasetRows(jobId, 'courses'),
  ])

  const programCode = new Map(programs.rows.map((p) => [p.program_id, p.program_code]))
  const courseName = new Map(courses.rows.map((c) => [c.course_id, c.course_name]))
  const studentProgram = new Map(students.rows.map((s) => [s.student_id, s.program_id]))

  const coursesByGroup = new Map<string, string[]>()
  for (const row of groupCourses.rows) {
    const list = coursesByGroup.get(row.elective_group_id) ?? []
    list.push(row.course_id)
    coursesByGroup.set(row.elective_group_id, list)
  }

  return groups.rows.map((g) => {
    const groupCourseIds = new Set(coursesByGroup.get(g.elective_group_id) ?? [])
    const enrolledStudentIds = new Set(
      enrollments.rows.filter((e) => groupCourseIds.has(e.course_id)).map((e) => e.student_id),
    )
    const countByProgram = new Map<string, number>()
    for (const sid of enrolledStudentIds) {
      const pid = studentProgram.get(sid)
      if (!pid) continue
      countByProgram.set(pid, (countByProgram.get(pid) ?? 0) + 1)
    }
    const byProgram = Array.from(countByProgram.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([pid, count]) => ({ label: programCode.get(pid) ?? pid, value: count }))

    return {
      id: g.elective_group_id,
      name: g.group_name,
      type: g.elective_type,
      year: g.year,
      courses: Array.from(groupCourseIds).map((cid) => courseName.get(cid) ?? cid),
      byProgram,
      total: enrolledStudentIds.size,
    }
  })
}

export function ElectivesPage() {
  const { jobId, hasSolved } = useJob()
  const navigate = useNavigate()
  const [groupViews, setGroupViews] = useState<ElectiveGroupView[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    setError(null)
    loadElectiveGroups(jobId)
      .then(setGroupViews)
      .catch(() => setError('Could not load elective enrollment data for this job.'))
      .finally(() => setLoading(false))
  }, [jobId])

  if (!jobId) {
    return (
      <>
        <PageHeader
          title="Electives"
          subtitle="Program Core Electives (PCE) and Open Area Electives (OAE) — the NEP2020 cross-programme flexibility the scheduler enforces at the individual-student level."
        />
        <Card>
          <EmptyState
            icon="book"
            title="No dataset loaded yet"
            description="Upload your data to see elective enrollment."
            action={<Button onClick={() => navigate('/upload')}>Upload data →</Button>}
          />
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Electives"
        subtitle="Real per-student enrollment, joined from students.csv + student_enrollments.csv + elective_groups.csv — not a schema field that goes unused."
      />
      {loading && <div>Loading…</div>}
      {error && <Banner tone="error" title="Couldn't load electives">{error}</Banner>}
      {!loading && !error && groupViews && groupViews.length === 0 && (
        <Card>
          <EmptyState icon="book" title="No elective groups" description="This dataset has no elective_groups.csv data." />
        </Card>
      )}
      {groupViews && groupViews.length > 0 && (
        <div className={styles.groupGrid}>
          {groupViews.map((g) => (
            <Card key={g.id}>
              <div className={styles.groupHeader}>
                <h3 className={styles.groupName}>{g.name}</h3>
                <span className={`${styles.badge} ${g.type === 'OAE' ? styles.badgeOae : styles.badgePce}`}>
                  {g.type} · Year {g.year}
                </span>
              </div>
              <p className={styles.courseList}>{g.courses.join(', ') || 'No courses linked'}</p>

              {g.byProgram.length > 1 ? (
                <>
                  <p className={styles.chartCaption}>
                    {g.total} students enrolled, across {g.byProgram.length} programmes
                  </p>
                  <BarChart bars={g.byProgram} height={100} />
                </>
              ) : g.byProgram.length === 1 ? (
                <p className={styles.singleProgram}>
                  {g.total} student{g.total === 1 ? '' : 's'}, all {g.byProgram[0].label}
                </p>
              ) : (
                <p className={styles.singleProgram}>No enrollments yet</p>
              )}
            </Card>
          ))}
        </div>
      )}
      {!hasSolved && groupViews && groupViews.length > 0 && (
        <Banner tone="warn" title="No schedule generated yet">
          This is enrollment data, not a schedule — generate a schedule to see these electives placed conflict-free
          on the timetable.
        </Banner>
      )}
    </>
  )
}
