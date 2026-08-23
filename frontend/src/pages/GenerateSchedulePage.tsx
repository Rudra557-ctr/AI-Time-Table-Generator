import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { useJobStatus } from '../hooks/useJobStatus'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { StatCard } from '../components/common/StatCard'
import { Button } from '../components/common/Button'
import { Banner } from '../components/common/Banner'
import { WeightSlider } from '../components/common/WeightSlider'
import { EmptyState } from '../components/common/EmptyState'
import { getWeightDefaults, solveJob } from '../api/endpoints'
import { SolveBlockedError } from '../api/client'
import { formatStatus, isPendingStatus } from '../utils/formatStatus'
import styles from './GenerateSchedulePage.module.css'

// Label shown to the user -> backend soft.DEFAULT_WEIGHTS key. Kept in this
// order deliberately (highest-priority terms first), matching soft.py's own
// tiering. A slider's "_excess" companion weight (SC02_gaps_excess,
// SC_facgaps_excess) isn't separately exposed here — it's set equal to its
// base weight on submit, since this UI shows one slider per soft-objective
// concept, not one per internal penalty variable.
const WEIGHT_FIELDS: { label: string; key: string }[] = [
  { label: 'Student gaps', key: 'SC02_gaps' },
  { label: 'Isolated classes', key: 'SC_isolated' },
  { label: 'Faculty preference', key: 'SC01_pref' },
  { label: 'Faculty gaps', key: 'SC_facgaps' },
  { label: 'Workload balance', key: 'SC09_balance' },
  { label: 'Marathon avoidance', key: 'SC05_consecutive' },
  { label: 'Spread across days', key: 'SC06_spread' },
  { label: 'Undesirable slots', key: 'SC08_undesirable' },
  { label: 'Building movement', key: 'SC11_building' },
  { label: 'Room wastage', key: 'SC03_wastage' },
]

const FALLBACK_DEFAULTS: Record<string, number> = {
  SC02_gaps: 10,
  SC02_gaps_excess: 10,
  SC_isolated: 10,
  SC01_pref: 8,
  SC09_balance: 5,
  SC05_consecutive: 4,
  SC06_spread: 4,
  SC08_undesirable: 2,
  SC11_building: 2,
  SC_facgaps: 2,
  SC_facgaps_excess: 2,
  SC03_wastage: 1,
}

export function GenerateSchedulePage() {
  const { jobId, uploadResult, markSolved } = useJob()
  const navigate = useNavigate()
  const [weights, setWeights] = useState<Record<string, number>>(FALLBACK_DEFAULTS)
  // This controls ONLY the soft-optimization phase (see generate() below —
  // the hard-constraint phase gets its own fixed, generous budget, not a
  // slice of this). Default kept small on purpose: this is meant as a fast
  // first draft, not the final result — "Optimize further" on the
  // Timetable page does the real structural work afterward (gap-repair,
  // then faculty/preference polish), so spending a long time polishing a
  // draft that's about to be reworked anyway is wasted time. Worst case if
  // this is too small, the result safely degrades to an unpolished-but-
  // valid schedule (HARD_ONLY_FALLBACK), never nothing.
  const [timeBudget, setTimeBudget] = useState(30)
  const [activeJob, setActiveJob] = useState(false)
  const [kickoffError, setKickoffError] = useState<string | null>(null)
  const [blockers, setBlockers] = useState<string[] | null>(null)
  const [log, setLog] = useState<string[]>([])
  const startedAt = useRef<number | null>(null)
  const [elapsed, setElapsed] = useState(0)

  const { status, isPolling } = useJobStatus(jobId, { enabled: activeJob, intervalMs: 1500 })

  useEffect(() => {
    getWeightDefaults()
      .then((d) => setWeights((prev) => ({ ...prev, ...d })))
      .catch(() => {
        /* fall back to FALLBACK_DEFAULTS already in state */
      })
  }, [])

  useEffect(() => {
    if (!activeJob) return
    const t = setInterval(() => {
      if (startedAt.current) setElapsed(Math.round((Date.now() - startedAt.current) / 1000))
    }, 1000)
    return () => clearInterval(t)
  }, [activeJob])

  useEffect(() => {
    if (!status) return
    if (!isPendingStatus(status.status)) {
      setActiveJob(false)
      appendLog(`Hard phase: ${status.hard_status ?? '—'} in ${status.hard_seconds ?? '—'}s`)
      appendLog(`Soft phase: ${status.soft_status ?? '—'} in ${status.soft_seconds ?? '—'}s`)
      appendLog(`Final status: ${status.status}`)
      if (status.status !== 'INFEASIBLE' && status.status !== 'UNKNOWN' && !status.status.startsWith('ERROR')) {
        markSolved()
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.status])

  function appendLog(line: string) {
    setLog((prev) => [...prev, line])
  }

  async function generate() {
    if (!jobId) return
    setKickoffError(null)
    setBlockers(null)
    setLog([])
    startedAt.current = Date.now()
    setElapsed(0)
    // Hard constraints get a fixed, generous budget, NOT a slice of the
    // user-facing "time budget" field — proving even one conflict-free
    // schedule exists can legitimately take much longer than optimizing it
    // (measured: 86s on a real 32-section/164-offering dataset), and unlike
    // the soft phase there's no safe fallback if this phase times out with
    // nothing found (status UNKNOWN — no timetable at all). 150s matches
    // the backend's own tuned default, with real margin above that 86s.
    // The "time budget" field only controls the soft-optimization phase,
    // which safely degrades to HARD_ONLY_FALLBACK (still valid, just
    // unpolished) if it runs out — a small number here is never dangerous.
    const hardTimeLimit = 150
    const softTimeLimit = timeBudget
    appendLog(`POST /api/solve — hard constraints (≤${hardTimeLimit}s, fixed), then soft optimization (≤${softTimeLimit}s).`)
    setActiveJob(true)
    try {
      await solveJob(jobId, { hardTimeLimit, softTimeLimit, weights })
      appendLog('Solve accepted — running in background.')
    } catch (e) {
      setActiveJob(false)
      if (e instanceof SolveBlockedError) {
        setBlockers(e.blockers)
        appendLog(`Blocked before solving: ${e.blockers.length} blocker(s) found.`)
      } else {
        setKickoffError(e instanceof Error ? e.message : 'Could not start the solve.')
      }
    }
  }

  const audit = uploadResult?.audit || {}
  const statusDisplay = useMemo(() => formatStatus(status?.status), [status?.status])
  const objectiveDisplay =
    status?.objective !== undefined && status?.objective !== null ? status.objective.toFixed(4) : 'Minimizing'

  if (!jobId) {
    return (
      <>
        <PageHeader title="Ready to generate." subtitle="Hard constraints are always enforced. Soft preferences are optimized using your weights below." />
        <Card>
          <EmptyState
            icon="play"
            title="Upload a dataset first"
            description="Generate Schedule needs uploaded courses, faculty, rooms and availability data to run against."
            action={<Button onClick={() => navigate('/upload')}>Go to upload →</Button>}
          />
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Ready to generate."
        subtitle="Hard constraints (no clashes, capacity, availability) are always enforced. Soft preferences are optimized using your weights below."
      />

      <div className={styles.layout}>
        <div className={styles.left}>
          <div className={styles.statGrid}>
            <StatCard label="Courses" value={audit.courses ?? '—'} />
            <StatCard label="Faculty" value={audit.faculty ?? '—'} />
            <StatCard label="Rooms" value={audit.rooms ?? '—'} />
            <StatCard label="Sections" value={audit.sections ?? '—'} />
          </div>

          <Card className={styles.budgetCard}>
            <div className={styles.budgetRow}>
              <label>
                Time budget{' '}
                <input
                  className={`${styles.budgetInput} mono`}
                  type="number"
                  min={30}
                  max={600}
                  value={timeBudget}
                  onChange={(e) => setTimeBudget(Number(e.target.value))}
                  disabled={activeJob}
                />{' '}
                seconds
              </label>
              <p className={styles.budgetHint}>
                Controls soft-preference optimization time (hard constraints always get a separate, generous fixed
                budget, since a schedule must exist before it can be polished). The solver usually uses the full
                time searching for a better schedule — lower this for a quick draft, raise it before a final run. If
                it runs out, you still get a valid, conflict-free schedule — just less optimized.
              </p>
            </div>

            {blockers && blockers.length > 0 && (
              <Banner tone="error" title={`${blockers.length} blocker(s) — fix these first`}>
                <ul>
                  {blockers.map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              </Banner>
            )}
            {kickoffError && <Banner tone="error" title="Could not start solve">{kickoffError}</Banner>}

            <Button onClick={generate} loading={activeJob} disabled={activeJob}>
              {activeJob ? 'Generating…' : 'Generate schedule'}
            </Button>

            {!isPolling && status && !isPendingStatus(status.status) && (
              <Button variant="secondary" onClick={() => navigate('/timetable')} style={{ marginLeft: 10 }}>
                View timetable →
              </Button>
            )}
          </Card>

          <Card>
            <h3 className={styles.weightsTitle}>Weights</h3>
            <div className={styles.sliders}>
              {WEIGHT_FIELDS.map((f) => (
                <WeightSlider
                  key={f.key}
                  label={f.label}
                  value={weights[f.key] ?? 0}
                  onChange={(v) =>
                    setWeights((prev) => ({
                      ...prev,
                      [f.key]: v,
                      ...(f.key === 'SC02_gaps' ? { SC02_gaps_excess: v } : {}),
                      ...(f.key === 'SC_facgaps' ? { SC_facgaps_excess: v } : {}),
                    }))
                  }
                />
              ))}
            </div>
          </Card>
        </div>

        <div className={styles.right}>
          <div className={styles.console}>
            <div className={styles.consoleTitleBar}>
              <span className="mono">CP-SAT SOLVER CONSOLE</span>
            </div>
            <div className={styles.consoleHeadline}>
              {activeJob
                ? 'Solving hard constraints → optimizing soft…'
                : status
                  ? statusDisplay.label
                  : 'Idle — configure parameters and generate.'}
            </div>
            <div className={styles.telemetry}>
              <div className={styles.tcell}>
                <div className={styles.tkey}>ELAPSED</div>
                <div className={`${styles.tval} mono`}>{activeJob ? `${elapsed}s` : status ? `${(status.hard_seconds ?? 0) + (status.soft_seconds ?? 0)}s` : '—'}</div>
              </div>
              <div className={styles.tcell}>
                <div className={styles.tkey}>OBJECTIVE</div>
                <div className={`${styles.tval} mono`}>{objectiveDisplay}</div>
              </div>
              <div className={styles.tcell}>
                <div className={styles.tkey}>HARD PHASE</div>
                <div className={`${styles.tval} mono`}>{status?.hard_status ?? (activeJob ? 'running' : '—')}</div>
              </div>
              <div className={styles.tcell}>
                <div className={styles.tkey}>SOFT PHASE</div>
                <div className={`${styles.tval} mono`}>{status?.soft_status ?? (activeJob ? 'queued' : '—')}</div>
              </div>
            </div>
            <div className={styles.consoleLog}>
              {log.length === 0 ? (
                <div className={styles.logLine}>[INFO] Solver idle. Configure parameters and generate.</div>
              ) : (
                log.map((l, i) => (
                  <div key={i} className={styles.logLine}>
                    [INFO] {l}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
