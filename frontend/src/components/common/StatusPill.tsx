import type { StatusTone } from '../../utils/formatStatus'
import { Icon } from './Icon'
import styles from './StatusPill.module.css'

export function StatusPill({ label, tone }: { label: string; tone: StatusTone }) {
  return (
    <span className={`${styles.pill} ${styles[tone]}`}>
      {tone === 'ok' && <Icon name="check" size={13} />}
      {tone === 'error' && <Icon name="alert" size={13} />}
      {label}
    </span>
  )
}
