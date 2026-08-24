import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { StatCard } from '../components/common/StatCard'
import { Button } from '../components/common/Button'
import { EmptyState } from '../components/common/EmptyState'
import { BarChart, type BarChartBar } from '../components/common/BarChart'
import { getReport } from '../api/endpoints'
import type { GapSegmentSummary, ReportResponse } from '../api/types'
import styles from './AnalyticsPage.module.css'

function dayTypeBars(s: GapSegmentSummary): BarChartBar[] {
  return [
    { label: 'Zero-gap days', value: s.zero_gap_days, tone: 'ok' },
    { label: 'One-gap days', value: s.one_gap_days, tone: 'accent' },
    { label: '2+ gap days', value: s.multi_gap_days, tone: 'warn' },
  ]
}

function runLengthBars(s: GapSegmentSummary): BarChartBar[] {
  return Object.entries(s.run_length_histogram)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([length, count]) => ({ label: length, value: count, tone: 'accent' }))
}

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
          <div className={styles.chartGrid}>
            <Card>
              <h4 className={styles.chartTitle}>Section-day breakdown</h4>
              <p className={styles.chartSubtitle}>How many section-days have zero, one, or 2+ internal gaps.</p>
              <BarChart bars={dayTypeBars(report.sections)} />
            </Card>
            <Card>
              <h4 className={styles.chartTitle}>Consecutive-class run lengths</h4>
              <p className={styles.chartSubtitle}>How many back-to-back periods sections typically run, per day.</p>
              <BarChart bars={runLengthBars(report.sections)} />
              <details className={styles.tableToggle}>
                <summary>View as table</summary>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>Run length (periods)</th>
                      <th>Occurrences</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runLengthBars(report.sections).map((b) => (
                      <tr key={b.label}>
                        <td>{b.label}</td>
                        <td className="mono">{b.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </Card>
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
          <div className={styles.chartGrid}>
            <Card>
              <h4 className={styles.chartTitle}>Faculty-day breakdown</h4>
              <p className={styles.chartSubtitle}>How many faculty-days have zero, one, or 2+ internal gaps.</p>
              <BarChart bars={dayTypeBars(report.faculty)} />
            </Card>
            <Card>
              <h4 className={styles.chartTitle}>Consecutive-class run lengths</h4>
              <p className={styles.chartSubtitle}>How many back-to-back periods faculty typically teach, per day.</p>
              <BarChart bars={runLengthBars(report.faculty)} />
              <details className={styles.tableToggle}>
                <summary>View as table</summary>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>Run length (periods)</th>
                      <th>Occurrences</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runLengthBars(report.faculty).map((b) => (
                      <tr key={b.label}>
                        <td>{b.label}</td>
                        <td className="mono">{b.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </Card>
          </div>
        </>
      )}
    </>
  )
}
