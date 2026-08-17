import { useState, useEffect, useRef } from 'react'
import toast from 'react-hot-toast'

interface Signal {
  time: string
  action: string
  symbol: string
  entry: string
  sl: string
  tp: string
  status: 'pending' | 'executed' | 'error'
  _retry?: string
}

interface AccountStatus {
  balance: number
  equity: number
  profit: number
  positions: number
  pending_orders: number
  server: string
  currency: string
}

interface Position {
  ticket: number
  symbol: string
  type: string
  volume: number
  entry: number
  sl: number | null
  tp: number | null
  current_price: number
  profit: number
  server?: string
}

interface PendingOrder {
  ticket: number
  symbol: string
  type: string
  volume: number
  price: number
  sl: number | null
  tp: number | null
  server?: string
}

interface AccountState {
  daily_pnl: number
  paused: boolean
  date: string
  profit_limit: number
  loss_limit: number
}

export default function Dashboard() {
  const [running, setRunning] = useState(false)
  const [stopped, setStopped] = useState(false)
  const [signals, setSignals] = useState<Signal[]>([])
  const [accounts, setAccounts] = useState<AccountStatus[]>([])
  const [positions, setPositions] = useState<Position[]>([])
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([])
  const [accountStates, setAccountStates] = useState<Record<string, AccountState>>({})
  const [retrying, setRetrying] = useState<Set<number>>(new Set())
  const togglingRef = useRef<Set<string>>(new Set())
  const [backendOnline, setBackendOnline] = useState(false)

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/status')
      const data = await res.json()
      setBackendOnline(true)
      setRunning(data.running)
      setStopped(data.stopped || false)
      if (data.signals) setSignals(data.signals.slice().reverse())
      if (data.accounts?.length > 0) {
        setAccounts(data.accounts)
        setPositions(data.positions || [])
        setPendingOrders(data.pending_orders || [])
        setAccountStates((prev) => {
          const next = { ...(data.account_states || {}) }
          for (const key of togglingRef.current) {
            if (prev[key] && next[key] && prev[key].paused !== next[key].paused) {
              next[key] = { ...next[key], paused: prev[key].paused }
            }
          }
          return next
        })
      } else if (data.account && Object.keys(data.account).length > 0) {
        setAccounts([data.account])
        setPositions(data.positions || [])
        setPendingOrders(data.pending_orders || [])
        setAccountStates((prev) => {
          const next = { ...(data.account_states || {}) }
          for (const key of togglingRef.current) {
            if (prev[key] && next[key] && prev[key].paused !== next[key].paused) {
              next[key] = { ...next[key], paused: prev[key].paused }
            }
          }
          return next
        })
      }
    } catch {
      setBackendOnline(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 2000)
    return () => clearInterval(interval)
  }, [])

  const sendAction = async (action: string) => {
    await fetch(`/api/${action}`, { method: 'POST' })
    await fetchStatus()
  }

  const toggleAccount = async (name: string, action: 'pause' | 'resume') => {
    togglingRef.current.add(name)
    setAccountStates((prev) => ({
      ...prev,
      [name]: { ...prev[name], paused: action === 'pause' },
    }))
    await fetch(`/api/${action}-account`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    togglingRef.current.delete(name)
  }

  const handleRetry = async (signal: Signal, index: number) => {
    if (!signal._retry) {
      toast.error('No hay datos para reintentar')
      return
    }
    try {
      const parsed = JSON.parse(signal._retry)
      setRetrying((prev) => new Set(prev).add(index))
      const res = await fetch('/api/retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed),
      })
      const data = await res.json()
      if (data.ok) {
        toast.success(`Reintentando ${parsed.symbol} ${parsed.action}`)
      } else {
        toast.error(data.error || 'Error al reintentar')
      }
    } catch {
      toast.error('Error al reintentar')
    } finally {
      setRetrying((prev) => {
        const next = new Set(prev)
        next.delete(index)
        return next
      })
    }
  }

  const positionType = (t: string) =>
    t === 'BUY' ? 'text-success' : 'text-danger'

  const orderTypeClass = (t: string) =>
    t.includes('BUY') ? 'text-success' : t.includes('SELL') ? 'text-danger' : 'text-yellow-400'

  const pnlClass = (v: number) =>
    v >= 0 ? 'text-success' : 'text-danger'

  // Estado visual
  let statusText = ''
  let statusColor = ''
  if (running && !stopped) {
    statusText = 'RUNNING'
    statusColor = 'border-brand text-brand'
  } else if (!running && !stopped) {
    statusText = 'PAUSADO'
    statusColor = 'border-yellow-500 text-yellow-400'
  } else {
    statusText = 'DETENIDO'
    statusColor = 'border-red-500 text-red-400'
  }

  return (
    <div className="space-y-4">
      {/* Header con botonera central */}
      <div className="text-center space-y-3">
        <h1 className="text-2xl font-bold">Dashboard</h1>

        {/* Indicador de estado */}
        <div className="flex items-center justify-center gap-2">
          <span className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border text-xs font-semibold uppercase tracking-wider ${statusColor}`}>
            <span className={`relative flex h-2.5 w-2.5 ${running ? '' : 'opacity-30'}`}>
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${running ? 'bg-brand' : 'bg-gray-500'}`} />
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${running ? 'bg-brand' : 'bg-gray-500'}`} />
            </span>
            {statusText}
          </span>
        </div>

        {/* Botones RUN / PAUSE / STOP */}
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => sendAction('start')}
            disabled={running && !stopped}
            className="px-8 py-3 rounded-xl font-bold text-lg transition-all duration-200
                       bg-brand hover:bg-brand-dark disabled:opacity-30 disabled:cursor-not-allowed
                       shadow-lg shadow-brand/20"
          >
            RUN
          </button>
          <button
            onClick={() => sendAction('pause')}
            disabled={!running || stopped}
            className="px-8 py-3 rounded-xl font-bold text-lg transition-all duration-200
                       bg-yellow-600 hover:bg-yellow-700 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            PAUSE
          </button>
          <button
            onClick={() => sendAction('stop')}
            disabled={stopped}
            className="px-8 py-3 rounded-xl font-bold text-lg transition-all duration-200
                       bg-red-600 hover:bg-red-700 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            STOP
          </button>
        </div>
      </div>

      {/* Conectividad */}
      <div className="flex items-center justify-center gap-4 text-[11px] text-gray-500">
        <span className="flex items-center gap-1">
          <span className={`w-2 h-2 rounded-full ${backendOnline ? 'bg-green-500' : 'bg-red-500'}`} />
          Backend
        </span>
        {accounts.map((acc) => {
          const name = acc.server || ''
          const online = Object.keys(accountStates).includes(name)
          return (
            <span key={name} className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${online ? 'bg-green-500' : 'bg-red-500'}`} />
              {name}
            </span>
          )
        })}
      </div>

      {/* Info */}
      <div className="card">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Info</h2>
        {accounts.length === 0 && Object.keys(accountStates).length === 0 ? (
          <p className="text-gray-500 text-xs">Sin datos de cuenta</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {accounts.map((acc) => {
              const name = acc.server || ''
              const st = accountStates[name] || { daily_pnl: 0, paused: false, profit_limit: 0, loss_limit: 0 }
              const accPositions = positions.filter((p) => p.server === name)
              const accOrders = pendingOrders.filter((o) => o.server === name)
              return (
                <div key={name} className="bg-surface-dark rounded-lg border border-gray-700 px-3 py-2 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-brand font-semibold text-sm truncate">{name}</span>
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${st.paused ? 'badge-red' : 'badge-green'}`}>
                        {st.paused ? 'PAUSADA' : 'ACTIVA'}
                      </span>
                      <button
                        onClick={() => toggleAccount(name, st.paused ? 'resume' : 'pause')}
                        className={`relative inline-flex h-4 w-8 items-center rounded-full transition-colors ${!st.paused ? 'bg-brand' : 'bg-gray-600'}`}
                        title={st.paused ? 'Reanudar' : 'Pausar'}
                      >
                        <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${!st.paused ? 'translate-x-[17px]' : 'translate-x-[2px]'}`} />
                      </button>
                    </div>
                  </div>
                  <div className="text-[11px] text-gray-400 space-y-0.5">
                    <div>Balance: <span className="text-gray-200">{acc.balance?.toFixed(2)} {acc.currency}</span></div>
                    <div>Equity: <span className="text-gray-200">{acc.equity?.toFixed(2)}</span></div>
                    <div>
                      P&L: <span className={pnlClass(acc.profit || 0)}>{acc.profit >= 0 ? '+' : ''}{acc.profit?.toFixed(2)}</span>
                      <span className="text-gray-500 ml-1">Hoy:</span>
                      <span className={pnlClass(st.daily_pnl)}>{st.daily_pnl >= 0 ? '+' : ''}{st.daily_pnl.toFixed(2)}</span>
                    </div>
                    <div>
                      Pos: {accPositions.length}
                      {st.profit_limit > 0 && <span className="text-gray-600 ml-1">/ +{st.profit_limit}</span>}
                      {st.loss_limit > 0 && <span className="text-gray-600 ml-1">/ -{st.loss_limit}</span>}
                    </div>
                    <div>Ord: {accOrders.length}</div>
                  </div>
                </div>
              )
            })}
            {/* Cuentas solo en tracking (no conectadas) */}
            {Object.entries(accountStates).map(([name, st]) => {
              if (accounts.some((a) => a.server === name)) return null
              return (
                <div key={name} className="bg-surface-dark rounded-lg border border-gray-700 px-3 py-2 space-y-1.5 opacity-60">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-400 font-semibold text-sm truncate">{name}</span>
                    <span className="badge-yellow text-[10px]">SIN CONEXION</span>
                  </div>
                  <div className="text-[11px] text-gray-500 space-y-0.5">
                    <div>Hoy: <span className={pnlClass(st.daily_pnl)}>{st.daily_pnl >= 0 ? '+' : ''}{st.daily_pnl.toFixed(2)}</span></div>
                    {st.profit_limit > 0 && <div>Limite profit: +{st.profit_limit}</div>}
                    {st.loss_limit > 0 && <div>Limite perdida: -{st.loss_limit}</div>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Señales recibidas */}
        <div className="card">
          <h2 className="text-lg font-semibold mb-3">Señales recibidas</h2>
          <div className="overflow-auto max-h-[60vh]">
            <table className="w-full text-xs">
              <thead className="text-gray-400 border-b border-gray-700 sticky top-0 bg-surface z-10">
                <tr>
                  <th className="text-left pb-2 pr-1">Hora</th>
                  <th className="text-left pb-2 pr-1">Par</th>
                  <th className="text-left pb-2 pr-1">Entry</th>
                  <th className="text-left pb-2 pr-1">SL</th>
                  <th className="text-left pb-2 pr-1">TP</th>
                  <th className="text-left pb-2 pr-1">Est.</th>
                  <th className="text-left pb-2">Acc.</th>
                </tr>
              </thead>
              <tbody>
                {signals.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-center py-8 text-gray-500">
                      Esperando señales...
                    </td>
                  </tr>
                )}
                {signals.map((s, i) => (
                  <tr key={i} className="border-b border-gray-800">
                    <td className="py-1.5 text-gray-400 pr-1 whitespace-nowrap">{s.time}</td>
                    <td className="py-1.5 pr-1">
                      <span className={s.action === 'BUY' ? 'text-success' : 'text-danger'}>
                        {s.symbol}
                      </span>
                    </td>
                    <td className="py-1.5 font-mono pr-1">{s.entry}</td>
                    <td className="py-1.5 font-mono pr-1">{s.sl}</td>
                    <td className="py-1.5 font-mono pr-1 text-gray-400 max-w-[80px] truncate">{s.tp}</td>
                    <td className="py-1.5 pr-1">
                      <span
                        className={
                          s.status === 'executed' ? 'badge-green'
                          : s.status === 'error' ? 'badge-red'
                          : 'badge-yellow'
                        }
                      >
                        {s.status}
                      </span>
                    </td>
                    <td className="py-1.5">
                      <button
                        onClick={() => handleRetry(s, i)}
                        disabled={retrying.has(i) || !s._retry || stopped || !running}
                        className="text-[10px] px-1.5 py-0.5 rounded border border-gray-600 hover:border-brand hover:text-brand transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                        title="Reintentar orden"
                      >
                        {retrying.has(i) ? '...' : 'Reintentar'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Posiciones y Órdenes */}
        <div className="space-y-4">
          {/* Posiciones abiertas */}
          <div className="card">
            <h2 className="text-lg font-semibold mb-3">
              Posiciones abiertas
              {positions.length > 0 && (
                <span className="text-sm text-gray-400 ml-2">({positions.length})</span>
              )}
            </h2>
            <div className="overflow-auto max-h-[28vh]">
              {positions.length === 0 ? (
                <p className="text-gray-500 text-sm py-4 text-center">Sin posiciones abiertas</p>
              ) : (
                <table className="w-full text-xs">
                  <thead className="text-gray-400 border-b border-gray-700 sticky top-0 bg-surface z-10">
                    <tr>
                      <th className="text-left pb-2 pr-1">Ticket</th>
                      <th className="text-left pb-2 pr-1">Par</th>
                      <th className="text-left pb-2 pr-1">Vol.</th>
                      <th className="text-left pb-2 pr-1">Entry</th>
                      <th className="text-left pb-2 pr-1">Cuenta</th>
                      <th className="text-right pb-2">P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={p.ticket} className="border-b border-gray-800">
                        <td className="py-1.5 text-gray-500 pr-1">#{p.ticket}</td>
                        <td className="py-1.5 pr-1">
                          <span className={positionType(p.type)}>
                            {p.type} {p.symbol}
                          </span>
                        </td>
                        <td className="py-1.5 pr-1">{p.volume}</td>
                        <td className="py-1.5 font-mono pr-1">{p.entry}</td>
                        <td className="py-1.5 pr-1 text-gray-500 text-[10px]">{p.server || '—'}</td>
                        <td className={`py-1.5 font-mono text-right ${pnlClass(p.profit)}`}>
                          {p.profit >= 0 ? '+' : ''}{p.profit.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* Órdenes pendientes */}
          <div className="card">
            <h2 className="text-lg font-semibold mb-3">
              Órdenes pendientes
              {pendingOrders.length > 0 && (
                <span className="text-sm text-gray-400 ml-2">({pendingOrders.length})</span>
              )}
            </h2>
            <div className="overflow-auto max-h-[28vh]">
              {pendingOrders.length === 0 ? (
                <p className="text-gray-500 text-sm py-4 text-center">Sin órdenes pendientes</p>
              ) : (
                <table className="w-full text-xs">
                  <thead className="text-gray-400 border-b border-gray-700 sticky top-0 bg-surface z-10">
                    <tr>
                      <th className="text-left pb-2 pr-1">Ticket</th>
                      <th className="text-left pb-2 pr-1">Par</th>
                      <th className="text-left pb-2 pr-1">Tipo</th>
                      <th className="text-left pb-2 pr-1">Vol.</th>
                      <th className="text-left pb-2 pr-1">Precio</th>
                      <th className="text-left pb-2 pr-1">Cuenta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pendingOrders.map((o) => (
                      <tr key={o.ticket} className="border-b border-gray-800">
                        <td className="py-1.5 text-gray-500 pr-1">#{o.ticket}</td>
                        <td className="py-1.5 pr-1 text-gray-300">{o.symbol}</td>
                        <td className="py-1.5 pr-1">
                          <span className={orderTypeClass(o.type)}>{o.type.replace('_', ' ')}</span>
                        </td>
                        <td className="py-1.5 pr-1">{o.volume}</td>
                        <td className="py-1.5 font-mono pr-1">{o.price}</td>
                        <td className="py-1.5 pr-1 text-gray-500 text-[10px]">{o.server || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
