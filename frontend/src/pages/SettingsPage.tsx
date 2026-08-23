import { useState } from 'react'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { getStoredApiKey, setStoredApiKey } from '../api/client'
import { useJob } from '../context/JobContext'
import styles from './SettingsPage.module.css'

export function SettingsPage() {
  const { jobId, clearJob } = useJob()
  const [apiKey, setApiKey] = useState(() => getStoredApiKey())
  const [saved, setSaved] = useState(false)

  function save() {
    setStoredApiKey(apiKey.trim())
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <>
      <PageHeader title="Settings" subtitle="Connection and session settings for this browser only." />

      <Card className={styles.section}>
        <h3 className={styles.title}>API key</h3>
        <p className={styles.desc}>
          Only needed if the backend was started with <code className="mono">SIH_API_KEY</code> set — sent as the{' '}
          <code className="mono">X-API-Key</code> header on every request. Leave blank for local development.
        </p>
        <div className={styles.row}>
          <input
            className={styles.input}
            type="password"
            placeholder="Not set"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <Button variant="secondary" onClick={save}>
            {saved ? 'Saved ✓' : 'Save'}
          </Button>
        </div>
      </Card>

      <Card className={styles.section}>
        <h3 className={styles.title}>Current session</h3>
        <p className={styles.desc}>
          {jobId ? (
            <>
              Working on job <code className="mono">{jobId}</code>. Clearing it forgets the reference locally — the
              backend still has the uploaded data and any generated timetable.
            </>
          ) : (
            'No dataset loaded.'
          )}
        </p>
        {jobId && (
          <Button variant="secondary" onClick={clearJob}>
            Clear current dataset
          </Button>
        )}
      </Card>

      <Card className={styles.section}>
        <h3 className={styles.title}>About</h3>
        <p className={styles.desc}>
          SmartSchedule generates conflict-free timetables with Google OR-Tools CP-SAT, then optimizes for compact,
          balanced schedules using a hierarchical (lexicographic) soft objective — higher-priority terms, like
          eliminating mid-day gaps, can never be traded away by lower-priority ones. Every status shown in this app
          (feasible vs. optimal, blockers, gap statistics) is read directly from the solver, never fabricated.
        </p>
      </Card>
    </>
  )
}
