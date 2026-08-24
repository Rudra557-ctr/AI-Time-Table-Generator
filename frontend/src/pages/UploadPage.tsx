import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { Banner } from '../components/common/Banner'
import { DataTable } from '../components/common/DataTable'
import { DataRequirementsGuide } from '../components/common/DataRequirementsGuide'
import { Icon } from '../components/common/Icon'
import { uploadFiles } from '../api/endpoints'
import { ApiError } from '../api/client'
import { useJob } from '../context/JobContext'
import styles from './UploadPage.module.css'

export function UploadPage() {
  const navigate = useNavigate()
  const { setJob, uploadResult, jobId } = useJob()
  const [files, setFiles] = useState<File[]>([])
  const [fill, setFill] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function addFiles(list: FileList | null) {
    if (!list) return
    setFiles((prev) => [...prev, ...Array.from(list)])
  }

  async function submit() {
    if (files.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const result = await uploadFiles(files, { fill })
      setJob(result.job_id, result)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Upload failed — check your connection to the backend.')
    } finally {
      setBusy(false)
    }
  }

  const warnings = extractWarnings(uploadResult?.report)

  return (
    <>
      <PageHeader
        title="Upload Data"
        subtitle="CSV, XLSX or a zipped folder — courses, faculty, rooms, availability and enrollment data. Column names are matched automatically, even if they don't exactly match our schema."
      />

      <Card>
        <div
          className={`${styles.dropzone} ${dragOver ? styles.dragOver : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            addFiles(e.dataTransfer.files)
          }}
        >
          <Icon name="upload" size={26} />
          <div className={styles.dropTitle}>Drop CSV / XLSX / ZIP files here, or click to browse</div>
          {files.length > 0 && <div className={styles.fileCount}>{files.length} files selected</div>}
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            accept=".csv,.xlsx,.xls,.zip"
            onChange={(e) => addFiles(e.target.files)}
          />
        </div>

        {files.length > 0 && (
          <ul className={styles.fileList}>
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`}>
                <span className="mono">{f.name}</span>
                <button
                  type="button"
                  className={styles.removeBtn}
                  onClick={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        <label className={styles.fillRow}>
          <input type="checkbox" checked={fill} onChange={(e) => setFill(e.target.checked)} />
          Fill missing files from the bundled sample dataset (demo convenience only — leave off for real data)
        </label>

        {error && <Banner tone="error" title="Upload failed">{error}</Banner>}

        <Button onClick={submit} loading={busy} disabled={files.length === 0}>
          {busy ? 'Uploading…' : 'Upload & analyze'}
        </Button>
      </Card>

      {!uploadResult && (
        <details className={styles.guideDetails}>
          <summary className={styles.guideSummary}>What data should I provide for an optimal timetable?</summary>
          <DataRequirementsGuide />
        </details>
      )}

      {uploadResult && (
        <>
          <h3 className={styles.sectionTitle}>What you should add for an optimal timetable</h3>
          <Card>
            <DataRequirementsGuide audit={uploadResult.audit} />
          </Card>

          <details className={styles.guideDetails}>
            <summary className={styles.guideSummary}>Raw ingestion audit (rows detected per dataset)</summary>
            <DataTable
              columns={['dataset', 'rows']}
              rows={Object.entries(uploadResult.audit).map(([dataset, rows]) => ({
                dataset,
                rows: String(rows),
              }))}
            />
          </details>

          {warnings.length > 0 && (
            <div className={styles.warningsBlock}>
              <Banner tone="warn" title={`${warnings.length} adapter warning${warnings.length > 1 ? 's' : ''}`}>
                <ul>
                  {warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </Banner>
            </div>
          )}

          <Button onClick={() => navigate('/generate')} disabled={!jobId}>
            Continue to Generate Schedule <Icon name="arrowRight" size={15} />
          </Button>
        </>
      )}
    </>
  )
}

function extractWarnings(report: unknown): string[] {
  if (!report) return []
  if (Array.isArray(report)) return report.map(String)
  if (typeof report === 'object') {
    const r = report as Record<string, unknown>
    if (Array.isArray(r.warnings)) return r.warnings.map(String)
    // Fall back to any array-valued field so an unexpected report shape
    // still surfaces something instead of silently showing nothing.
    for (const v of Object.values(r)) {
      if (Array.isArray(v) && v.every((x) => typeof x === 'string')) return v
    }
  }
  return []
}
