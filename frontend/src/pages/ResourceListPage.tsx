import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJob } from '../context/JobContext'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/common/Card'
import { Button } from '../components/common/Button'
import { EmptyState } from '../components/common/EmptyState'
import { DataTable } from '../components/common/DataTable'
import { getDatasetRows } from '../api/endpoints'
import type { IconName } from '../components/common/Icon'

const ICONS: Record<string, IconName> = { sections: 'users', faculty: 'cap', rooms: 'door', courses: 'book' }

export function ResourceListPage({ dataset, title }: { dataset: string; title: string }) {
  const { jobId } = useJob()
  const navigate = useNavigate()
  const [rows, setRows] = useState<Record<string, string>[] | null>(null)
  const [columns, setColumns] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    setError(null)
    getDatasetRows(jobId, dataset)
      .then((res) => {
        setRows(res.rows)
        setColumns(res.rows.length > 0 ? Object.keys(res.rows[0]) : [])
      })
      .catch(() => setError(`${dataset}.csv wasn't found in this upload.`))
      .finally(() => setLoading(false))
  }, [jobId, dataset])

  if (!jobId) {
    return (
      <>
        <PageHeader title={title} subtitle={`Real ${dataset} data from your uploaded dataset — read-only.`} />
        <Card>
          <EmptyState
            icon={ICONS[dataset] ?? 'grid'}
            title="No dataset loaded yet"
            description="Upload your data to see this list."
            action={<Button onClick={() => navigate('/upload')}>Upload data →</Button>}
          />
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={title}
        subtitle={`${rows ? rows.length : '…'} rows from ${dataset}.csv, as ingested — read-only.`}
      />
      <Card>
        {loading && <div>Loading…</div>}
        {error && (
          <EmptyState
            icon={ICONS[dataset] ?? 'grid'}
            title={`No ${dataset}.csv in this dataset`}
            description="This file wasn't part of the last upload for this job."
          />
        )}
        {rows && rows.length > 0 && <DataTable columns={columns} rows={rows} />}
        {rows && rows.length === 0 && (
          <EmptyState icon={ICONS[dataset] ?? 'grid'} title="Empty" description={`${dataset}.csv has no rows.`} />
        )}
      </Card>
    </>
  )
}
