import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { Banner } from '../components/common/Banner'
import { EmptyState } from '../components/common/EmptyState'
import { getPrecheck } from '../api/endpoints'
import type { PrecheckResponse } from '../api/types'

export function ConflictsPage() {
  const { jobId } = useJob()
  const navigate = useNavigate()
  const [precheck, setPrecheck] = useState<PrecheckResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    getPrecheck(jobId)
      .then(setPrecheck)
      .catch(() => setError('Could not run the structural check for this job.'))
      .finally(() => setLoading(false))
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
      <Card>
        {loading && <div>Checking…</div>}
        {error && <Banner tone="error" title="Check failed">{error}</Banner>}
        {precheck && (
          <>
            {precheck.blockers.length === 0 ? (
              <Banner tone="ok" title="0 blockers — data is structurally solvable" />
            ) : (
              <Banner tone="error" title={`${precheck.blockers.length} blocker(s) — solving will fail until these are fixed`}>
                <ul>
                  {precheck.blockers.map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              </Banner>
            )}
            {precheck.warnings.length > 0 && (
              <Banner tone="warn" title={`${precheck.warnings.length} warning(s) — non-blocking`}>
                <ul>
                  {precheck.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </Banner>
            )}
          </>
        )}
      </Card>
    </>
  )
}
