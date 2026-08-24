import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { Banner } from '../components/common/Banner'
import { StatusPill } from '../components/common/StatusPill'
import { EmptyState } from '../components/common/EmptyState'
import { Icon } from '../components/common/Icon'
import { Modal } from '../components/common/Modal'
import { deleteJob, listJobs } from '../api/endpoints'
import { formatStatus } from '../utils/formatStatus'
import type { JobSummary } from '../api/types'
import styles from './HistoryPage.module.css'

const RECENT_LIMIT = 5

function formatWhen(createdAt: number): string {
  if (!createdAt) return 'Unknown time'
  const d = new Date(createdAt * 1000)
  const diffMin = (Date.now() - d.getTime()) / 60000
  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${Math.round(diffMin)} min ago`
  if (diffMin < 24 * 60) return `${Math.round(diffMin / 60)} hr ago`
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function DatasetChip({ label, value }: { label: string; value: number | null }) {
  if (value === null || value === undefined) return null
  return (
    <span className={styles.chip}>
      <span className={styles.chipValue}>{value}</span> {label}
    </span>
  )
}

export function HistoryPage() {
  const { jobId, switchJob, clearJob } = useJob()
  const navigate = useNavigate()
  const [jobs, setJobs] = useState<JobSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [pendingDelete, setPendingDelete] = useState<JobSummary | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    listJobs(RECENT_LIMIT)
      .then((res) => setJobs(res.jobs))
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load recent timetables.'))
      .finally(() => setLoading(false))
  }, [])

  function handleView(job: JobSummary) {
    switchJob(job.job_id, job.has_timetable)
    navigate('/timetable')
  }

  async function confirmDelete() {
    if (!pendingDelete) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteJob(pendingDelete.job_id)
      setJobs((prev) => (prev ? prev.filter((j) => j.job_id !== pendingDelete.job_id) : prev))
      // The deleted job was the one the rest of the app is currently
      // pointed at (context + localStorage) — clear it so /timetable and
      // friends don't keep trying to load data that no longer exists.
      if (pendingDelete.job_id === jobId) clearJob()
      setPendingDelete(null)
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : 'Could not delete this timetable.')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Recent Timetables"
        subtitle={`Your last ${RECENT_LIMIT} generated schedules — reopen any of them anytime.`}
      />

      {error && (
        <Banner tone="error" title="Could not load history">
          {error}
        </Banner>
      )}

      {loading && <div className={styles.loading}>Loading recent timetables…</div>}

      {!loading && jobs && jobs.length === 0 && (
        <Card>
          <EmptyState
            icon="history"
            title="No timetables generated yet"
            description="Upload a dataset and run a solve — it will show up here so you can come back to it later."
            action={<Button onClick={() => navigate('/upload')}>Upload data →</Button>}
          />
        </Card>
      )}

      {!loading && jobs && jobs.length > 0 && (
        <div className={styles.grid}>
          {jobs.map((job) => {
            const statusDisplay = formatStatus(job.status ?? undefined)
            const isCurrent = job.job_id === jobId
            return (
              <Card key={job.job_id} className={isCurrent ? styles.currentCard : ''}>
                <div className={styles.cardHead}>
                  <span className={`${styles.jobId} mono`}>{job.job_id}</span>
                  <div className={styles.headActions}>
                    {isCurrent && <span className={styles.currentBadge}>Current</span>}
                    <button
                      type="button"
                      className={styles.deleteIconBtn}
                      title="Delete this timetable"
                      aria-label="Delete this timetable"
                      onClick={() => setPendingDelete(job)}
                    >
                      <Icon name="trash" size={15} />
                    </button>
                  </div>
                </div>

                <div className={styles.when}>
                  <Icon name="calendar" size={13} />
                  {formatWhen(job.created_at)}
                </div>

                <div className={styles.pillRow}>
                  <StatusPill label={statusDisplay.label} tone={statusDisplay.tone} />
                  {job.publish_state && (
                    <StatusPill
                      label={job.publish_state === 'published' ? 'Published' : 'Draft'}
                      tone={job.publish_state === 'published' ? 'ok' : 'pending'}
                    />
                  )}
                </div>

                <div className={styles.chipRow}>
                  <DatasetChip label="sections" value={job.sections} />
                  <DatasetChip label="faculty" value={job.faculty} />
                  <DatasetChip label="rooms" value={job.rooms} />
                  <DatasetChip label="courses" value={job.courses} />
                </div>

                <div className={styles.viewRow}>
                  <Button
                    variant={isCurrent ? 'secondary' : 'primary'}
                    disabled={!job.has_timetable}
                    title={job.has_timetable ? undefined : 'This job has no generated timetable yet'}
                    onClick={() => handleView(job)}
                  >
                    {job.has_timetable ? 'View timetable' : 'Not yet solved'}
                    {job.has_timetable && <Icon name="arrowRight" size={14} />}
                  </Button>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {pendingDelete && (
        <Modal
          title="Delete this timetable?"
          onClose={() => (deleting ? null : setPendingDelete(null))}
          footer={
            <>
              <Button variant="secondary" onClick={() => setPendingDelete(null)} disabled={deleting}>
                Cancel
              </Button>
              <button type="button" className={styles.confirmDeleteBtn} onClick={confirmDelete} disabled={deleting}>
                {deleting ? 'Deleting…' : 'Delete permanently'}
              </button>
            </>
          }
        >
          <p className={styles.confirmText}>
            This permanently removes job <span className="mono">{pendingDelete.job_id}</span> — its uploaded
            data, generated timetable, and edit history. This cannot be undone.
          </p>
          {pendingDelete.job_id === jobId && (
            <p className={styles.confirmWarn}>
              This is your currently open job — deleting it will also clear it from the app.
            </p>
          )}
          {deleteError && (
            <Banner tone="error" title="Delete failed">
              {deleteError}
            </Banner>
          )}
        </Modal>
      )}
    </>
  )
}
