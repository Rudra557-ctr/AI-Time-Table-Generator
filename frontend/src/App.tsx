import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { JobProvider } from './context/JobContext'
import { AppShell } from './components/layout/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { UploadPage } from './pages/UploadPage'
import { TimetablePage } from './pages/TimetablePage'
import { GenerateSchedulePage } from './pages/GenerateSchedulePage'
import { HistoryPage } from './pages/HistoryPage'
import { ResourceListPage } from './pages/ResourceListPage'
import { ElectivesPage } from './pages/ElectivesPage'
import { ConflictsPage } from './pages/ConflictsPage'
import { AnalyticsPage } from './pages/AnalyticsPage'

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
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/sections" element={<ResourceListPage dataset="sections" title="Sections" />} />
            <Route path="/faculty" element={<ResourceListPage dataset="faculty" title="Faculty" />} />
            <Route path="/rooms" element={<ResourceListPage dataset="rooms" title="Rooms" />} />
            <Route path="/courses" element={<ResourceListPage dataset="courses" title="Courses" />} />
            <Route path="/electives" element={<ElectivesPage />} />
            <Route path="/conflicts" element={<ConflictsPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </JobProvider>
  )
}
