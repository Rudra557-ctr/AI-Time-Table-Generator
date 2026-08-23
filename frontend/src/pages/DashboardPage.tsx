import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { StatCard } from '../components/common/StatCard'
import { Card } from '../components/common/Card'
import { ProgressBar } from '../components/common/ProgressBar'
import { StatusPill } from '../components/common/StatusPill'
import { EmptyState } from '../components/common/EmptyState'
import { Button } from '../components/common/Button'
import { Icon } from '../components/common/Icon'
import { DataTable } from '../components/common/DataTable'
import { getPrecheck, getStatus } from '../api/endpoints'
import { fetchTimetableCsvText } from '../api/endpoints'
import { computeDashboardStats, todayDayCode, type DashboardStats } from '../utils/csv'
import { formatStatus } from '../utils/formatStatus'
import type { PrecheckResponse, StatusResponse } from '../api/types'
import styles from './DashboardPage.module.css'

export function DashboardPage() {
  const { jobId, uploadResult } = useJob()
  const navigate = useNavigate()
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [precheck, setPrecheck] = useState<PrecheckResponse | null>(null)
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    Promise.all([getStatus(jobId).catch(() => null), getPrecheck(jobId).catch(() => null)]).then(
      ([s, p]) => {
        setStatus(s)
        setPrecheck(p)
        setLoading(false)
      },
    )
  }, [jobId])

  useEffect(() => {
    if (!jobId || !status?.output) return
    const audit = status.audit || uploadResult?.audit || {}
    fetchTimetableCsvText(jobId)
      .then((text) =>
        setStats(computeDashboardStats(text, audit.faculty || 0, audit.rooms || 0, audit.time_slots || 1)),
      )
      .catch(() => setStats(null))
  }, [jobId, status, uploadResult])

  if (!jobId) {
    return (
      <>
        <PageHeader title="University Scheduling Overview" subtitle="Monitor schedules, resources and conflicts across the university." />
        <Card>
          <EmptyState
            icon="upload"
            title="No dataset loaded yet"
            description="Upload your courses, faculty, rooms and availability data to see live scheduling metrics here."
            action={<Button onClick={() => navigate('/upload')}>Upload data →</Button>}
          />
        </Card>
      </>
    )
  }

  const audit = status?.audit || uploadResult?.audit || {}
  const statusDisplay = formatStatus(status?.status)
  const today = todayDayCode()
  const isWeekend = today === 'SAT' || today === 'SUN'

  return (
    <>
      <PageHeader
        title="University Scheduling Overview"
        subtitle="Monitor schedules, resources and conflicts across the university."
      />

      <div className={styles.statRow}>
        <StatCard label="Scheduled Sessions" value={stats ? stats.sessionCount : '—'} />
        <StatCard
          label="Faculty"
          value={audit.faculty ?? '—'}
          suffix={stats ? `${stats.facultyUtilizationPct}% util` : undefined}
        />
        <StatCard
          label="Rooms"
          value={audit.rooms ?? '—'}
          suffix={stats ? `${stats.roomUtilizationPct}% util` : undefined}
        />
        <StatCard label="Sections" value={audit.sections ?? stats?.sectionCount ?? '—'} />
        <StatCard
          label="Conflicts"
          value={precheck ? precheck.blockers.length : loading ? '—' : 0}
          tone={precheck && precheck.blockers.length > 0 ? 'error' : 'ok'}
        />
      </div>

      <div className={styles.grid}>
        <Card>
          <div className={styles.cardHead}>
            <h3 className={styles.cardTitle}>Today's Schedule</h3>
            <span className={`${styles.dateTag} mono`}>{today} · —</span>
          </div>
          {isWeekend || !stats ? (
            <EmptyState
              icon="calendar"
              title="It's the weekend — no classes scheduled."
              description={!isWeekend && !stats ? 'Run a solve to populate today’s agenda.' : undefined}
            />
          ) : (
            <div className={styles.todaySummary}>
              <div className={styles.todayCount}>{stats.todayCount}</div>
              <div>
                <div className={styles.todayLabel}>sessions scheduled today</div>
                <Button variant="secondary" onClick={() => navigate('/timetable')}>
                  View timetable →
                </Button>
              </div>
            </div>
          )}
        </Card>

        <Card>
          <h3 className={styles.cardTitle}>System Health</h3>
          <div className={styles.healthStatus}>
            <div className={styles.healthLabel}>Schedule Status</div>
            <StatusPill label={statusDisplay.label} tone={statusDisplay.tone} />
          </div>
          <div className={styles.utilRow}>
            <div className={styles.utilLabel}>
              <span>Faculty Utilization</span>
              <span className="mono">{stats ? `${stats.facultyUtilizationPct}%` : '—'}</span>
            </div>
            <ProgressBar value={stats?.facultyUtilizationPct ?? 0} />
          </div>
          <div className={styles.utilRow}>
            <div className={styles.utilLabel}>
              <span>Room Utilization</span>
              <span className="mono">{stats ? `${stats.roomUtilizationPct}%` : '—'}</span>
            </div>
            <ProgressBar value={stats?.roomUtilizationPct ?? 0} />
          </div>
          <div className={styles.blockerCard}>
            <Icon name="gear" size={16} />
            <div>
              <div className={styles.blockerValue}>{precheck ? precheck.blockers.length : '—'}</div>
              <div className={styles.blockerLabel}>Solver Blockers</div>
            </div>
          </div>
        </Card>
      </div>

      {Object.keys(audit).length > 0 && (
        <>
          <h3 className={styles.sectionTitle}>Dataset overview</h3>
          <Card>
            <DataTable
              columns={['dataset', 'rows']}
              rows={Object.entries(audit)
                .filter(([, v]) => v > 0)
                .map(([name, count]) => ({ dataset: name, rows: String(count) }))}
            />
          </Card>
        </>
      )}
    </>
  )
}
