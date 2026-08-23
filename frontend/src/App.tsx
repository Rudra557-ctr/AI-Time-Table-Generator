import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { JobProvider } from './context/JobContext'
import { AppShell } from './components/layout/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { UploadPage } from './pages/UploadPage'
import { TimetablePage } from './pages/TimetablePage'
import { GenerateSchedulePage } from './pages/GenerateSchedulePage'
import { ResourceListPage } from './pages/ResourceListPage'
import { ConflictsPage } from './pages/ConflictsPage'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { SettingsPage } from './pages/SettingsPage'

export default function App() {
  return (
    <JobProvider>
      <BrowserRouter>
        <AppShell>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/timetable" element={<TimetablePage />} />
            <Route path="/generate" element={<GenerateSchedulePage />} />
            <Route path="/sections" element={<ResourceListPage dataset="sections" title="Sections" />} />
            <Route path="/faculty" element={<ResourceListPage dataset="faculty" title="Faculty" />} />
            <Route path="/rooms" element={<ResourceListPage dataset="rooms" title="Rooms" />} />
            <Route path="/courses" element={<ResourceListPage dataset="courses" title="Courses" />} />
            <Route path="/conflicts" element={<ConflictsPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </JobProvider>
  )
}
