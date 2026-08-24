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
import styles from './ResourceListPage.module.css'

const ICONS: Record<string, IconName> = { sections: 'users', faculty: 'cap', rooms: 'door', courses: 'book' }

export function ResourceListPage({ dataset, title }: { dataset: string; title: string }) {
  const { jobId } = useJob()
  const navigate = useNavigate()
  const [rows, setRows] = useState<Record<string, string>[] | null>(null)
  const [columns, setColumns] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    setError(null)
    setSearch('')
    getDatasetRows(jobId, dataset)
      .then((res) => {
        setRows(res.rows)
        setColumns(res.rows.length > 0 ? Object.keys(res.rows[0]) : [])
      })
      .catch(() => setError(`${dataset}.csv wasn't found in this upload.`))
      .finally(() => setLoading(false))
  }, [jobId, dataset])

  const query = search.trim().toLowerCase()
  const filteredRows = query
    ? (rows ?? []).filter((row) => Object.values(row).some((v) => v.toLowerCase().includes(query)))
    : rows

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
        {rows && rows.length > 0 && (
          <input
            className={styles.search}
            type="text"
            placeholder={`Search ${dataset}…`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        )}
        {filteredRows && filteredRows.length > 0 && <DataTable columns={columns} rows={filteredRows} />}
        {rows && rows.length > 0 && filteredRows && filteredRows.length === 0 && (
          <EmptyState icon={ICONS[dataset] ?? 'grid'} title="No matches" description={`No rows match "${search}".`} />
        )}
        {rows && rows.length === 0 && (
          <EmptyState icon={ICONS[dataset] ?? 'grid'} title="Empty" description={`${dataset}.csv has no rows.`} />
        )}
      </Card>
    </>
  )
}
