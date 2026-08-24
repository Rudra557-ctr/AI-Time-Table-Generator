import { NavLink } from 'react-router-dom'
import { Icon, type IconName } from '../common/Icon'
import styles from './Sidebar.module.css'

const NAV_ITEMS: { to: string; label: string; icon: IconName }[] = [
  { to: '/', label: 'Dashboard', icon: 'grid' },
  { to: '/upload', label: 'Upload Data', icon: 'upload' },
  { to: '/timetable', label: 'Timetable', icon: 'calendar' },
  { to: '/generate', label: 'Generate Schedule', icon: 'play' },
  { to: '/history', label: 'History', icon: 'history' },
  { to: '/sections', label: 'Sections', icon: 'users' },
  { to: '/faculty', label: 'Faculty', icon: 'cap' },
  { to: '/rooms', label: 'Rooms', icon: 'door' },
  { to: '/courses', label: 'Courses', icon: 'book' },
  { to: '/electives', label: 'Electives', icon: 'users' },
  { to: '/conflicts', label: 'Conflicts', icon: 'alert' },
]

const NAV_ITEMS_LOWER: { to: string; label: string; icon: IconName }[] = [
  { to: '/analytics', label: 'Analytics', icon: 'chart' },
]

export function Sidebar() {
  return (
    <aside className={`${styles.sidebar} no-print`}>
      <div className={styles.brand}>
        <span className={styles.brandMark}>
          <Icon name="grid" size={16} />
        </span>
        SmartSchedule
      </div>
      <nav className={styles.nav}>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ''}`}
          >
            <Icon name={item.icon} size={17} />
            {item.label}
          </NavLink>
        ))}
        <div className={styles.spacer} />
        {NAV_ITEMS_LOWER.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ''}`}
          >
            <Icon name={item.icon} size={17} />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className={styles.footer}>
        <div className={styles.avatar}>A</div>
        <div>
          <div className={styles.footerName}>Admin</div>
          <div className={styles.footerSub}>USAR GGSIPU</div>
        </div>
      </div>
    </aside>
  )
}
