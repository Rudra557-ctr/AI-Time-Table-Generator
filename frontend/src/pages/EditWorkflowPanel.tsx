import { useEffect, useState } from 'react'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { Banner } from '../components/common/Banner'
import { StatusPill } from '../components/common/StatusPill'
import { Icon } from '../components/common/Icon'
import {
  getEditHistory,
  getStatus,
  publishTimetable,
  undoLastEdit,
  validateAllEdits,
} from '../api/endpoints'
import { EditRejectedError, PublishBlockedError } from '../api/client'
import type { EditHistoryEntry, ValidateAllResponse } from '../api/types'
import styles from './EditWorkflowPanel.module.css'

function snapshotLabel(s: EditHistoryEntry['before']) {
  if (!s) return '—'
  return `${s.day} ${s.start_time} · ${s.room_id} · ${s.faculty_id}`
}

export function EditWorkflowPanel({
  jobId,
  refreshKey,
  onChanged,
}: {
  jobId: string
  refreshKey: number
  onChanged: () => void
}) {
  const [history, setHistory] = useState<EditHistoryEntry[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [undoing, setUndoing] = useState(false)
  const [undoError, setUndoError] = useState<string | null>(null)

  const [validating, setValidating] = useState(false)
  const [validateResult, setValidateResult] = useState<ValidateAllResponse | null>(null)
  const [validateError, setValidateError] = useState<string | null>(null)

  const [publishing, setPublishing] = useState(false)
  const [publishError, setPublishError] = useState<string | null>(null)
  const [publishState, setPublishState] = useState<'draft' | 'published'>('draft')

  useEffect(() => {
    setLoadingHistory(true)
    getEditHistory(jobId)
      .then(({ history }) => setHistory(history))
      .finally(() => setLoadingHistory(false))
    getStatus(jobId)
      .then((s) => setPublishState(s.publish_state ?? 'draft'))
      .catch(() => {})
    // A fresh edit invalidates any earlier "Validate Final Timetable" run —
    // its verdict no longer describes the current schedule.
    setValidateResult(null)
  }, [jobId, refreshKey])

  const latestUndoable = [...history].reverse().find((h) => h.kind !== 'undo' && !h.undone)

  async function submitUndo() {
    setUndoing(true)
    setUndoError(null)
    try {
      await undoLastEdit(jobId)
      onChanged()
    } catch (e) {
      if (e instanceof EditRejectedError) setUndoError(e.violations[0] || e.message)
      else setUndoError(e instanceof Error ? e.message : 'Could not undo.')
    } finally {
      setUndoing(false)
    }
  }

  async function submitValidate() {
    setValidating(true)
    setValidateError(null)
    try {
      setValidateResult(await validateAllEdits(jobId))
    } catch (e) {
      setValidateError(e instanceof Error ? e.message : 'Could not validate.')
    } finally {
      setValidating(false)
    }
  }

  async function submitPublish() {
    setPublishing(true)
    setPublishError(null)
    try {
      await publishTimetable(jobId)
      setPublishState('published')
    } catch (e) {
      if (e instanceof PublishBlockedError) setPublishError(e.message)
      else setPublishError(e instanceof Error ? e.message : 'Could not publish.')
    } finally {
      setPublishing(false)
    }
  }

  return (
    <>
      <h3 className={styles.sectionTitle}>Admin edits &amp; publishing</h3>
      <Card>
        <div className={styles.header}>
          <StatusPill
            label={publishState === 'published' ? 'Published' : 'Draft'}
            tone={publishState === 'published' ? 'ok' : 'pending'}
          />
          <span className={styles.headerHint}>
            {publishState === 'published'
              ? 'This is the version shown as the final timetable.'
              : 'Not yet published — validate and publish when ready.'}
          </span>
        </div>

        {!loadingHistory && history.length === 0 && (
          <p className={styles.hint}>
            No manual edits yet. Click any scheduled class in the grid above to move it, change its room, or
            reassign faculty.
          </p>
        )}

        {history.length > 0 && (
          <div className={styles.historyScroller}>
            <table className={styles.historyTable}>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Class</th>
                  <th>Change</th>
                  <th>Impact</th>
                </tr>
              </thead>
              <tbody>
                {[...history].reverse().map((h) => (
                  <tr key={h.id} className={h.undone ? styles.undoneRow : ''}>
                    <td className="mono">{new Date(h.timestamp * 1000).toLocaleTimeString()}</td>
                    <td className="mono">
                      {h.offering_id}#{h.session}
                      {h.undone ? ' (undone)' : ''}
                    </td>
                    <td className="mono">
                      {snapshotLabel(h.before)} <span className={styles.arrow}>→</span> {snapshotLabel(h.after)}
                    </td>
                    <td className="mono">
                      {h.weighted_delta > 0 ? '+' : ''}
                      {h.weighted_delta}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {latestUndoable && (
          <div className={styles.actionsRow}>
            <Button variant="secondary" onClick={submitUndo} loading={undoing}>
              <Icon name="undo" size={14} /> Undo last edit
            </Button>
          </div>
        )}
        {undoError && (
          <Banner tone="error" title="Undo rejected">
            {undoError}
          </Banner>
        )}

        <div className={styles.actionsRow}>
          <Button variant="secondary" onClick={submitValidate} loading={validating}>
            Validate final timetable
          </Button>
          <Button
            onClick={submitPublish}
            loading={publishing}
            disabled={!validateResult?.clean || publishState === 'published'}
          >
            {publishState === 'published' ? 'Published' : 'Publish timetable'}
          </Button>
        </div>
        {validateError && (
          <Banner tone="error" title="Validation failed">
            {validateError}
          </Banner>
        )}
        {publishError && (
          <Banner tone="error" title="Cannot publish">
            {publishError}
          </Banner>
        )}

        {validateResult && (
          <>
            <Banner
              tone={validateResult.clean ? 'ok' : 'error'}
              title={
                validateResult.clean
                  ? 'Timetable is valid and ready to publish'
                  : `${validateResult.violations.length} hard-constraint violation(s)`
              }
            >
              {!validateResult.clean && (
                <ul>
                  {validateResult.violations.slice(0, 10).map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                  {validateResult.violations.length > 10 && <li>… and {validateResult.violations.length - 10} more.</li>}
                </ul>
              )}
              {validateResult.warnings.length > 0 && <p>{validateResult.warnings.length} warning(s) — not blocking.</p>}
            </Banner>
            {validateResult.soft_quality && (
              <div className={styles.softSummary}>
                Quality — section gaps: <span className="mono">{validateResult.soft_quality.sections.total_gaps}</span> ·
                faculty gaps: <span className="mono">{validateResult.soft_quality.faculty.total_gaps}</span> · sessions
                checked: <span className="mono">{validateResult.sessions_checked}</span>
              </div>
            )}
          </>
        )}
      </Card>
    </>
  )
}
