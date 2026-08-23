import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { ThemeToggle } from './ThemeToggle'
import { useJob } from '../../context/JobContext'
import styles from './AppShell.module.css'

export function AppShell({ children }: { children: ReactNode }) {
  const { jobId } = useJob()
  return (
    <div className={styles.shell}>
      <Sidebar />
      <div className={styles.mainCol}>
        <header className={styles.topbar}>
          <span className={`${styles.jobBadge} mono`}>
            {jobId ? `job ${jobId}` : 'no dataset loaded'}
          </span>
          <ThemeToggle />
        </header>
        <main className={styles.main}>{children}</main>
      </div>
    </div>
  )
}
