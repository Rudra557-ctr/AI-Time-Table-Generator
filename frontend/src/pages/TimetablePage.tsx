import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { useJobStatus } from '../hooks/useJobStatus'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { Banner } from '../components/common/Banner'
import { EmptyState } from '../components/common/EmptyState'
import { Icon } from '../components/common/Icon'
import {
  fetchTimetableCsvText,
  getDownloadClassPath,
  getDownloadPath,
  getReport,
  optimizeJob,
  resolveJob,
} from '../api/endpoints'
import { downloadWithAuth } from '../utils/download'
import { formatChangedKey, parseClassGridCsv, parseSectionIds, type ClassGrid } from '../utils/csv'
import { ResolveRequiresSolveError, SolveBlockedError } from '../api/client'
import { isPendingStatus } from '../utils/formatStatus'
import type { ChangedEntry, ReportResponse } from '../api/types'
import styles from './TimetablePage.module.css'

const OPTIMIZE_ROWS: { label: string; pick: (r: ReportResponse) => number }[] = [
  { label: 'Total internal gaps (sections)', pick: (r) => r.sections.total_gaps },
  { label: 'Section-days with 2+ gaps', pick: (r) => r.sections.multi_gap_days },
  { label: 'Isolated single-period classes', pick: (r) => r.sections.total_isolated_runs },
  { label: 'Faculty total gaps', pick: (r) => r.faculty.total_gaps },
]

export function TimetablePage() {
  const { jobId, hasSolved } = useJob()
  const navigate = useNavigate()
  const [sections, setSections] = useState<string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [grid, setGrid] = useState<ClassGrid | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [resolveFiles, setResolveFiles] = useState<File[]>([])
  const [resolving, setResolving] = useState(false)
  const [resolveError, setResolveError] = useState<string | null>(null)
  const [resolveBlockers, setResolveBlockers] = useState<string[] | null>(null)
  const [changed, setChanged] = useState<ChangedEntry[] | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const [optimizing, setOptimizing] = useState(false)
  const [polish, setPolish] = useState(false)
  const [optimizeError, setOptimizeError] = useState<string | null>(null)
  const [beforeReport, setBeforeReport] = useState<ReportResponse | null>(null)
  const [afterReport, setAfterReport] = useState<ReportResponse | null>(null)
  const optimizeStarted = useRef<number | null>(null)
  const [optimizeElapsed, setOptimizeElapsed] = useState(0)

  const { status: resolveStatus } = useJobStatus(jobId, { enabled: resolving, intervalMs: 1500 })
  const { status: optimizeStatus } = useJobStatus(jobId, { enabled: optimizing, intervalMs: 3000 })

  useEffect(() => {
    if (!optimizing) return
    const t = setInterval(() => {
      if (optimizeStarted.current) setOptimizeElapsed(Math.round((Date.now() - optimizeStarted.current) / 1000))
    }, 1000)
    return () => clearInterval(t)
  }, [optimizing])

  useEffect(() => {
    if (!optimizeStatus) return
    if (!isPendingStatus(optimizeStatus.status)) {
      setOptimizing(false)
      if (jobId) {
        getReport(jobId).then(setAfterReport).catch(() => {})
        if (selected) {
          fetch(getDownloadClassPath(jobId, selected))
            .then((r) => r.text())
            .then((text) => setGrid(parseClassGridCsv(text)))
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optimizeStatus?.status])

  async function submitOptimize() {
    if (!jobId) return
    setOptimizeError(null)
    setAfterReport(null)
    optimizeStarted.current = Date.now()
    setOptimizeElapsed(0)
    try {
      const before = await getReport(jobId)
      setBeforeReport(before)
    } catch {
      setBeforeReport(null)
    }
    setOptimizing(true)
    try {
      await optimizeJob(jobId, { polish })
    } catch (e) {
      setOptimizing(false)
      setOptimizeError(e instanceof Error ? e.message : 'Could not start optimization.')
    }
  }

  useEffect(() => {
    if (!jobId || !hasSolved) return
    fetchTimetableCsvText(jobId)
      .then((text) => {
        const ids = parseSectionIds(text)
        setSections(ids)
        setSelected((prev) => prev ?? ids[0] ?? null)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load timetable.'))
  }, [jobId, hasSolved])

  useEffect(() => {
    if (!jobId || !selected) return
    setLoading(true)
    fetch(getDownloadClassPath(jobId, selected))
      .then((r) => {
        if (!r.ok) throw new Error(`No grid for section ${selected}`)
        return r.text()
      })
      .then((text) => setGrid(parseClassGridCsv(text)))
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load section grid.'))
      .finally(() => setLoading(false))
  }, [jobId, selected])

  useEffect(() => {
    if (!resolveStatus) return
    if (!isPendingStatus(resolveStatus.status)) {
      setResolving(false)
      if (resolveStatus.changed) setChanged(resolveStatus.changed)
      // Refresh the grid for the currently selected section with the new solve.
      if (jobId && selected) {
        fetch(getDownloadClassPath(jobId, selected))
          .then((r) => r.text())
          .then((text) => setGrid(parseClassGridCsv(text)))
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolveStatus?.status])

  async function submitResolve() {
    if (!jobId || resolveFiles.length === 0) return
    setResolving(true)
    setResolveError(null)
    setResolveBlockers(null)
    setChanged(null)
    try {
      await resolveJob(jobId, resolveFiles)
    } catch (e) {
      setResolving(false)
      if (e instanceof SolveBlockedError) setResolveBlockers(e.blockers)
      else if (e instanceof ResolveRequiresSolveError) setResolveError('No previous solve found — generate a schedule first.')
      else setResolveError(e instanceof Error ? e.message : 'Could not start the re-solve.')
    }
  }

  if (!jobId || !hasSolved) {
    return (
      <>
        <PageHeader title="Timetable" subtitle="Per-section schedule grids, generated by the CP-SAT solver." />
        <Card>
          <EmptyState
            icon="calendar"
            title={!jobId ? 'No dataset loaded yet' : 'No schedule generated yet'}
            description={!jobId ? 'Upload your data to get started.' : 'Run Generate Schedule to produce a timetable first.'}
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
        title="Timetable"
        subtitle="Every section's schedule, straight from the solver — the same view works as the admin dashboard and the student/faculty portal."
        action={
          jobId && (
            <Button variant="secondary" onClick={() => downloadWithAuth(getDownloadPath(jobId), 'timetable.csv')}>
              <Icon name="download" size={14} /> Download full timetable
            </Button>
          )
        }
      />

      {error && <Banner tone="error" title="Couldn't load timetable">{error}</Banner>}

      <div className={styles.chipRow}>
        {sections.map((s) => (
          <button
            key={s}
            className={`${styles.chip} ${selected === s ? styles.chipActive : ''}`}
            onClick={() => setSelected(s)}
          >
            {s}
          </button>
        ))}
      </div>

      <Card>
        {loading || !grid ? (
          <div className={styles.loading}>Loading grid…</div>
        ) : (
          <div className={styles.scroller}>
            <table className={styles.grid}>
              <thead>
                <tr>
                  <th>Day</th>
                  {grid.periodHeaders.map((h) => (
                    <th key={h} className="mono">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {grid.rows.map((row) => (
                  <tr key={row.day}>
                    <td className={styles.dayCell}>{row.day}</td>
                    {row.cells.map((cell, i) => {
                      const changedHere = changed?.some((c) => cell !== '—' && c.new && cell.includes(c.new))
                      return (
                        <td
                          key={i}
                          className={`${styles.slotCell} mono ${cell === '—' ? styles.empty : ''} ${changedHere ? styles.changedCell : ''}`}
                        >
                          {cell}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {jobId && selected && (
          <div className={styles.downloadRow}>
            <Button
              variant="ghost"
              onClick={() => downloadWithAuth(getDownloadClassPath(jobId, selected), `${selected}.csv`)}
            >
              <Icon name="download" size={14} /> Download {selected} only
            </Button>
          </div>
        )}
      </Card>

      <h3 className={styles.sectionTitle}>Optimize further</h3>
      <Card>
        <p className={styles.resolveDesc}>
          This schedule is valid, but generated fast. Optimizing further repairs section gaps one at a time — the
          biggest visible win, validated to cut internal gaps ~80% on a real dataset — in{' '}
          <strong>typically ~2 minutes</strong>.
        </p>
        <label className={styles.polishRow}>
          <input type="checkbox" checked={polish} onChange={(e) => setPolish(e.target.checked)} disabled={optimizing} />
          Also polish faculty-compactness and preferences afterward — adds ~3 more minutes, worth it once you're not
          racing a clock (e.g. before a final export), skip it for a live demo
        </label>
        <div className={styles.resolveRow}>
          <Button onClick={submitOptimize} loading={optimizing} disabled={optimizing}>
            {optimizing ? `Optimizing… (${optimizeElapsed}s elapsed)` : 'Optimize further'}
          </Button>
        </div>

        {optimizeError && <Banner tone="error" title="Could not optimize">{optimizeError}</Banner>}

        {optimizing && (
          <Banner tone="warn" title={`Still running — ${optimizeElapsed}s of a typical ~${polish ? 300 : 120}s elapsed`}>
            The grid above is the OLD schedule and will look unchanged until this finishes — it refreshes
            automatically the moment it's done. Working through gap-structure first, then faculty-compactness, then
            everything else, in that strict order. Safe to leave this tab open and check back in a few minutes.
          </Banner>
        )}

        {!optimizing && optimizeStatus && Boolean(optimizeStatus.tier_results) && (
          <div className={styles.tierRow}>
            {Object.entries(optimizeStatus.tier_results as Record<string, { status: string }>).map(([tier, r]) => (
              <span key={tier} className={`${styles.tierBadge} ${r.status === 'FEASIBLE' || r.status === 'OPTIMAL' ? styles.tierOk : styles.tierBad}`}>
                {tier}: {r.status}
              </span>
            ))}
          </div>
        )}

        {beforeReport && afterReport && (
          <div className={styles.diffScroller}>
            <table className={styles.diffTable}>
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Before</th>
                  <th>After</th>
                </tr>
              </thead>
              <tbody>
                {OPTIMIZE_ROWS.map((row) => {
                  const before = row.pick(beforeReport)
                  const after = row.pick(afterReport)
                  const better = after < before
                  return (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      <td className="mono">{before}</td>
                      <td className={`mono ${better ? styles.betterCell : ''}`}>{after}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <h3 className={styles.sectionTitle}>Modify &amp; re-solve</h3>
      <Card>
        <p className={styles.resolveDesc}>
          Changed one thing — a room, a faculty member's availability, a course offering? Upload only the changed
          file. The solver re-solves minimizing how much of the existing schedule moves, instead of re-deciding
          everything from scratch.
        </p>
        <div className={styles.resolveRow}>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setResolveFiles(e.target.files ? Array.from(e.target.files) : [])}
          />
          <Button onClick={submitResolve} loading={resolving} disabled={resolveFiles.length === 0}>
            {resolving ? 'Re-solving…' : 'Re-solve'}
          </Button>
        </div>

        {resolveBlockers && resolveBlockers.length > 0 && (
          <Banner tone="error" title={`${resolveBlockers.length} blocker(s) — fix these first`}>
            <ul>
              {resolveBlockers.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          </Banner>
        )}
        {resolveError && <Banner tone="error" title="Re-solve failed">{resolveError}</Banner>}

        {resolveStatus?.tier_results !== undefined && !isPendingStatus(resolveStatus.status) && (
          <Banner tone="ok" title={`${resolveStatus.changed_count ?? changed?.length ?? 0} change(s) out of the existing schedule`}>
            final tier reached: {resolveStatus.final_tier_reached} · total time: {resolveStatus.total_seconds}s
          </Banner>
        )}

        {changed && changed.length > 0 && (
          <div className={styles.diffScroller}>
            <table className={styles.diffTable}>
              <thead>
                <tr>
                  <th>Kind</th>
                  <th>Session</th>
                  <th>Before → After</th>
                </tr>
              </thead>
              <tbody>
                {changed.map((c, i) => (
                  <tr key={i}>
                    <td className="mono">{c.kind}</td>
                    <td className="mono">{formatChangedKey(c.key)}</td>
                    <td className="mono">
                      {c.old} <span className={styles.arrow}>→</span> {c.new}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {changed && changed.length === 0 && (
          <Banner tone="ok" title="Nothing changed">The re-solve kept every existing assignment.</Banner>
        )}
      </Card>
    </>
  )
}
