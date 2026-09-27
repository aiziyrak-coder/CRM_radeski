import { lazy, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router'
import Layout from './components/Layout'
import { useAuth } from './lib/auth-context'
import { NAV_ITEMS, type NavItem } from './lib/navigation'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import SoonPage from './pages/SoonPage'

// pages load on demand: the first screen doesn't pay for every module
const AuditPage = lazy(() => import('./pages/AuditPage'))
const CallsPage = lazy(() => import('./pages/CallsPage'))
const QaPage = lazy(() => import('./pages/QaPage'))
const InboxPage = lazy(() => import('./pages/InboxPage'))
const CampaignsPage = lazy(() => import('./pages/CampaignsPage'))
const CampaignDetailPage = lazy(() => import('./pages/CampaignDetailPage'))
const IntegrationsPage = lazy(() => import('./pages/IntegrationsPage'))
const LeadsPage = lazy(() => import('./pages/LeadsPage'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))
const TasksPage = lazy(() => import('./pages/TasksPage'))
const DiagnosesPage = lazy(() => import('./pages/DiagnosesPage'))
const MyDayPage = lazy(() => import('./pages/MyDayPage'))
const PatientCardPage = lazy(() => import('./pages/PatientCardPage'))
const PatientsPage = lazy(() => import('./pages/PatientsPage'))
const ProfilePage = lazy(() => import('./pages/ProfilePage'))
const SchedulePage = lazy(() => import('./pages/SchedulePage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const UsersPage = lazy(() => import('./pages/UsersPage'))

const PAGES: Record<string, ReactNode> = {
  '/': <HomePage />,
  '/users': <UsersPage />,
  '/audit': <AuditPage />,
  '/profile': <ProfilePage />,
  '/patients': <PatientsPage />,
  '/diagnoses': <DiagnosesPage />,
  '/schedule': <SchedulePage />,
  '/my-day': <MyDayPage />,
  '/settings': <SettingsPage />,
  '/tasks': <TasksPage />,
  '/leads': <LeadsPage />,
  '/campaigns': <CampaignsPage />,
  '/reports': <ReportsPage />,
  '/calls': <CallsPage />,
  '/qa': <QaPage />,
  '/inbox': <InboxPage />,
  '/integrations': <IntegrationsPage />,
}

// detail pages inherit the roles of their menu section
const DETAIL_ROUTES: { path: string; section: string; element: ReactNode }[] = [
  { path: '/patients/:id', section: '/patients', element: <PatientCardPage /> },
  { path: '/campaigns/:id', section: '/campaigns', element: <CampaignDetailPage /> },
]

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return null
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

function Guarded({ item, children }: { item: NavItem; children?: ReactNode }) {
  const { user } = useAuth()
  if (!user || !item.roles.includes(user.role)) return <Navigate to="/" replace />
  return children ?? PAGES[item.path] ?? <SoonPage labelKey={item.labelKey} />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          {NAV_ITEMS.map((item) => (
            <Route key={item.path} path={item.path} element={<Guarded item={item} />} />
          ))}
          {DETAIL_ROUTES.map((r) => (
            <Route
              key={r.path}
              path={r.path}
              element={<Guarded item={NAV_ITEMS.find((i) => i.path === r.section)!}>{r.element}</Guarded>}
            />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
