import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { StatCard } from '../components/common/StatCard'
import { Button } from '../components/common/Button'
import { EmptyState } from '../components/common/EmptyState'
import { getReport } from '../api/endpoints'
import type { ReportResponse } from '../api/types'
import styles from './AnalyticsPage.module.css'

export function AnalyticsPage() {
  const { jobId, hasSolved } = useJob()
  const navigate = useNavigate()
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!jobId || !hasSolved) return
    setLoading(true)
    getReport(jobId)
      .then(setReport)
      .catch(() => setError('Report not available for this job yet.'))
      .finally(() => setLoading(false))
  }, [jobId, hasSolved])

  if (!jobId || !hasSolved) {
    return (
      <>
        <PageHeader title="Analytics" subtitle="Gap and compactness statistics, computed independently from the solved timetable." />
        <Card>
          <EmptyState
            icon="chart"
            title={!jobId ? 'No dataset loaded yet' : 'No schedule generated yet'}
            description="Generate a schedule first — analytics reads directly from the solved timetable."
            action={
              <Button onClick={() => navigate(!jobId ? '/upload' : '/generate')}>
                {!jobId ? 'Upload data →' : 'Generate schedule →'}
              </Button>
            }
          />
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Analytics"
        subtitle="Independent gap/compactness statistics — computed directly from occupancy, not the solver grading its own homework."
      />
      {loading && <div>Loading…</div>}
      {error && (
        <Card>
          <EmptyState icon="chart" title="Report not ready" description={error} />
        </Card>
      )}
      {report && (
        <>
          <h3 className={styles.sectionTitle}>Sections</h3>
          <div className={styles.statGrid}>
            <StatCard label="Section-days" value={report.sections.entity_days} />
            <StatCard label="Mean gaps / day" value={report.sections.mean_gaps_per_day.toFixed(2)} />
            <StatCard
              label="Zero-gap days"
              value={`${((100 * report.sections.zero_gap_days) / Math.max(report.sections.entity_days, 1)).toFixed(0)}%`}
              tone="ok"
            />
            <StatCard label="Isolated single-period runs" value={report.sections.total_isolated_runs} />
          </div>
          <h3 className={styles.sectionTitle}>Faculty</h3>
          <div className={styles.statGrid}>
            <StatCard label="Faculty-days" value={report.faculty.entity_days} />
            <StatCard label="Mean gaps / day" value={report.faculty.mean_gaps_per_day.toFixed(2)} />
            <StatCard
              label="2+ gap days"
              value={`${report.faculty.multi_gap_day_pct.toFixed(0)}%`}
              tone={report.faculty.multi_gap_day_pct > 20 ? 'warn' : 'ok'}
            />
            <StatCard label="Mean working days" value={report.faculty.mean_working_days.toFixed(1)} />
          </div>
        </>
      )}
    </>
  )
}
