import { Routes, Route, NavLink } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import Dashboard from './pages/Dashboard.tsx'
import Settings from './pages/Settings.tsx'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/settings', label: 'Configuración' },
]

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <Toaster position="top-right" toastOptions={{ style: { background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155' } }} />
      <nav className="bg-surface border-b border-gray-700 px-6 py-3 flex items-center gap-6">
        <span className="text-brand font-bold text-lg">TelBot</span>
        <span className="text-[10px] text-gray-500 bg-surface-dark px-1.5 py-0.5 rounded">v2.24</span>
        {navItems.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `text-sm transition-colors ${isActive ? 'text-brand' : 'text-gray-400 hover:text-gray-200'}`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <main className="flex-1 p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}
