import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { Banner } from '../components/common/Banner'
import { StatCard } from '../components/common/StatCard'
import { EmptyState } from '../components/common/EmptyState'
import { Icon } from '../components/common/Icon'
import { getPrecheck, getStatus } from '../api/endpoints'
import { suggestFix } from '../utils/conflictSuggestions'
import { formatStatus } from '../utils/formatStatus'
import type { PrecheckResponse } from '../api/types'
import styles from './ConflictsPage.module.css'

export function ConflictsPage() {
  const { jobId } = useJob()
  const navigate = useNavigate()
  const [precheck, setPrecheck] = useState<PrecheckResponse | null>(null)
  const [lastRunLabel, setLastRunLabel] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    getPrecheck(jobId)
      .then(setPrecheck)
      .catch(() => setError('Could not run the structural check for this job.'))
      .finally(() => setLoading(false))
    getStatus(jobId)
      .then((s) => setLastRunLabel(formatStatus(s.status).label))
      .catch(() => setLastRunLabel(null))
  }, [jobId])

  if (!jobId) {
    return (
      <>
        <PageHeader title="Conflicts" subtitle="Structural problems the solver would hit, found before spending any solve time." />
        <Card>
          <EmptyState
            icon="alert"
            title="No dataset loaded yet"
            description="Upload your data to run a solvability check."
            action={<Button onClick={() => navigate('/upload')}>Upload data →</Button>}
          />
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Conflicts"
        subtitle="A sub-second structural check (quick_solvability_check) — the same one that runs before any real solve, exposed here on its own."
      />

      {error && <Banner tone="error" title="Check failed">{error}</Banner>}

      <div className={styles.statRow}>
        <StatCard
          label="Critical Blockers"
          value={precheck ? precheck.blockers.length : loading ? '—' : 0}
          tone={precheck && precheck.blockers.length > 0 ? 'error' : 'ok'}
          icon="alert"
        />
        <StatCard
          label="Dataset Warnings"
          value={precheck ? precheck.warnings.length : loading ? '—' : 0}
          tone={precheck && precheck.warnings.length > 0 ? 'warn' : 'ok'}
          icon="alert"
        />
        <StatCard label="Last Run" value={lastRunLabel ?? '—'} tone="neutral" icon="check" />
      </div>

      <Card>
        <div className={styles.issuesHead}>
          <h3 className={styles.issuesTitle}>Active Issues</h3>
          {precheck && (
            <span className={styles.countPill}>
              Showing {precheck.blockers.length + precheck.warnings.length} items
            </span>
          )}
        </div>

        {loading && <div className={styles.loading}>Checking…</div>}

        {precheck && precheck.blockers.length === 0 && precheck.warnings.length === 0 && (
          <EmptyState
            icon="check"
            tone="ok"
            title="No conflicts detected"
            description="Hard constraints are enforced by the solver; any dataset issues would appear here."
          />
        )}

        {precheck && (precheck.blockers.length > 0 || precheck.warnings.length > 0) && (
          <ul className={styles.issueList}>
            {precheck.blockers.map((b, i) => {
              const fix = suggestFix(b)
              return (
                <li key={`b-${i}`} className={styles.issueRow}>
                  <span className={`${styles.issueIcon} ${styles.issueIconError}`}>
                    <Icon name="alert" size={14} />
                  </span>
                  <div>
                    <div className={styles.issueText}>{b}</div>
                    {fix && <div className={styles.fix}>Suggested fix: {fix}</div>}
                  </div>
                </li>
              )
            })}
            {precheck.warnings.map((w, i) => {
              const fix = suggestFix(w)
              return (
                <li key={`w-${i}`} className={styles.issueRow}>
                  <span className={`${styles.issueIcon} ${styles.issueIconWarn}`}>
                    <Icon name="alert" size={14} />
                  </span>
                  <div>
                    <div className={styles.issueText}>{w}</div>
                    {fix && <div className={styles.fix}>Suggested fix: {fix}</div>}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Card>
    </>
  )
}
