import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Papa from 'papaparse'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { StatCard } from '../components/common/StatCard'
import { Button } from '../components/common/Button'
import { EmptyState } from '../components/common/EmptyState'
import { BarChart, type BarChartBar } from '../components/common/BarChart'
import { getReport, getDatasetRows, fetchTimetableCsvText } from '../api/endpoints'
import { computeFacultyWorkload, type FacultyWorkload } from '../utils/workload'
import type { GapSegmentSummary, ReportResponse, TimetableRow } from '../api/types'
import styles from './AnalyticsPage.module.css'

const WORKLOAD_BUCKETS: { label: string; test: (pct: number) => boolean }[] = [
  { label: '0-25%', test: (p) => p < 25 },
  { label: '25-50%', test: (p) => p >= 25 && p < 50 },
  { label: '50-75%', test: (p) => p >= 50 && p < 75 },
  { label: '75-100%', test: (p) => p >= 75 && p <= 100 },
  { label: '100%+', test: (p) => p > 100 },
]

function workloadBucketBars(workload: FacultyWorkload[]): BarChartBar[] {
  return WORKLOAD_BUCKETS.map((b) => ({
    label: b.label,
    value: workload.filter((w) => b.test(w.pct)).length,
    tone: b.label === '100%+' ? 'warn' : 'accent',
  }))
}

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
  const [workload, setWorkload] = useState<FacultyWorkload[] | null>(null)
  const [workloadError, setWorkloadError] = useState<string | null>(null)

  useEffect(() => {
    if (!jobId || !hasSolved) return
    setLoading(true)
    getReport(jobId)
      .then(setReport)
      .catch(() => setError('Report not available for this job yet.'))
      .finally(() => setLoading(false))
  }, [jobId, hasSolved])

  useEffect(() => {
    if (!jobId || !hasSolved) return
    Promise.all([fetchTimetableCsvText(jobId), getDatasetRows(jobId, 'faculty')])
      .then(([csvText, facultyRes]) => {
        const parsed = Papa.parse<TimetableRow>(csvText, { header: true, skipEmptyLines: true })
        setWorkload(computeFacultyWorkload(parsed.data, facultyRes.rows))
      })
      .catch(() => setWorkloadError('Faculty workload data not available for this job yet.'))
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

          <h3 className={styles.sectionTitle}>Faculty Workload</h3>
          {workloadError && <Card><EmptyState icon="cap" title="Not available" description={workloadError} /></Card>}
          {workload && workload.length > 0 && (
            <>
              <div className={styles.statGrid}>
                <StatCard
                  label="Mean utilization"
                  value={`${Math.round(workload.reduce((s, w) => s + w.pct, 0) / workload.length)}%`}
                />
                <StatCard
                  label="Over-loaded (>100%)"
                  value={workload.filter((w) => w.pct > 100).length}
                  tone={workload.some((w) => w.pct > 100) ? 'error' : 'ok'}
                />
                <StatCard
                  label="Under-utilized (<50%)"
                  value={workload.filter((w) => w.pct < 50).length}
                  tone="warn"
                />
                <StatCard
                  label="Well-balanced (50-100%)"
                  value={workload.filter((w) => w.pct >= 50 && w.pct <= 100).length}
                  tone="ok"
                />
              </div>
              <div className={styles.chartGrid}>
                <Card>
                  <h4 className={styles.chartTitle}>Utilization distribution</h4>
                  <p className={styles.chartSubtitle}>Faculty count by assigned-hours ÷ max-hours-per-week bucket.</p>
                  <BarChart bars={workloadBucketBars(workload)} />
                </Card>
                <Card>
                  <h4 className={styles.chartTitle}>Most-loaded faculty</h4>
                  <p className={styles.chartSubtitle}>Top 5 by utilization — real assigned hours vs. their weekly max.</p>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Faculty</th>
                        <th>Hours</th>
                        <th>Utilization</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...workload]
                        .sort((a, b) => b.pct - a.pct)
                        .slice(0, 5)
                        .map((w) => (
                          <tr key={w.faculty_id}>
                            <td>
                              {w.name} <span className={styles.idTag}>({w.faculty_id})</span>
                            </td>
                            <td className="mono">
                              {w.assignedHours}/{w.maxHours}h
                            </td>
                            <td className="mono">{w.pct}%</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </Card>
              </div>
            </>
          )}
        </>
      )}
    </>
  )
}
