import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'

interface GlobalConfig {
  telegram_api_id: string
  telegram_api_hash: string
  telegram_phone: string
  signal_channel: string
  forward_chat_id: string
  control_chat_id: string
  github_repo: string
  github_branch: string
  polling_interval: number
  message_limit: number
  dry_run: boolean
  confirm_trades: boolean
  saved_channels: { id: string; name: string }[]
}

interface AccountConfig {
  id: string
  name: string
  login: string
  password: string
  server: string
  terminal_path: string
  instance_id: string
  risk_percent: number
  max_lot_size: number
  min_lot_size: number
  default_magic: string
  order_comment: string
  daily_profit_limit: number
  daily_loss_limit: number
  random_offset_ticks: number
  rr_ratio: number
  tp_index: number
  order_retry_count: number
  order_retry_delay: number
  anti_reverse: boolean
  enabled: boolean
}

interface Config {
  global: GlobalConfig
  accounts: AccountConfig[]
}

export default function Settings() {
  const [config, setConfig] = useState<Config | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const [testingForward, setTestingForward] = useState(false)
  const [showChannelModal, setShowChannelModal] = useState(false)
  const [chModalId, setChModalId] = useState('')
  const [chModalName, setChModalName] = useState('')
  const [showPasswords, setShowPasswords] = useState<Set<string>>(new Set())

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data) => {
        if (data.global && data.accounts !== undefined) {
          setConfig(data)
          setCollapsed(new Set([0, 1, 2]))
        } else {
          setConfig({ global: data as unknown as GlobalConfig, accounts: [] })
        }
      })
      .catch(() => toast.error('No se pudo cargar la configuracion'))
  }, [])

  const updateGlobal = (key: string, value: any) => {
    if (!config) return
    setConfig({
      ...config,
      global: { ...config.global, [key]: value },
    })
  }

  const updateAccount = (index: number, key: string, value: any) => {
    if (!config) return
    const accounts = [...config.accounts]
    accounts[index] = { ...accounts[index], [key]: value }
    setConfig({ ...config, accounts })
  }

  const save = async () => {
    if (!config) return
    setSaving(true)
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      if (res.ok) {
        toast.success('Configuracion guardada')
      } else {
        const data = await res.json()
        toast.error(data.error || 'Error al guardar')
      }
    } catch {
      toast.error('Error al guardar')
    } finally {
      setSaving(false)
    }
  }

  const testAccount = async (acc: AccountConfig) => {
    if (!acc.login || !acc.password || !acc.server) {
      toast.error('Rellena login, password y servidor')
      return
    }
    setTesting(acc.id)
    try {
      const res = await fetch('/api/test-account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          login: acc.login,
          password: acc.password,
          server: acc.server,
          terminal_path: acc.terminal_path,
        }),
      })
      const data = await res.json()
      if (data.success) {
        toast.success(`Balance: ${data.balance.toFixed(2)} ${data.currency} | Login: ${data.login}`)
      } else {
        toast.error(data.error || 'Error al conectar')
      }
    } catch {
      toast.error('Error al testear')
    } finally {
      setTesting(null)
    }
  }

  const testForward = async () => {
    if (!g.forward_chat_id) { toast.error('Configura el chat de reenvio primero'); return }
    setTestingForward(true)
    try {
      const res = await fetch('/api/test-forward', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: g.forward_chat_id }),
      })
      if (res.ok) toast.success('Mensaje de prueba enviado')
      else toast.error('Error al enviar')
    } catch { toast.error('Error al enviar') }
    finally { setTestingForward(false) }
  }

  const channelCombo = (label: string, value: string, onChange: (v: string) => void, desc?: string) => {
    const channels = g.saved_channels || []
    const selected = channels.find((ch) => ch.id === value)
    const empty = !value
    return (
      <div>
        <label className={`text-xs block mb-1 ${empty ? 'text-red-400' : 'text-gray-400'}`}>{label}</label>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={`input bg-surface-dark ${empty ? 'border-red-500/50 focus:border-red-400' : ''}`}
        >
          <option value="">-- Seleccionar --</option>
          {channels.map((ch, i) => (
            <option key={i} value={ch.id}>{ch.name}</option>
          ))}
        </select>
        {selected && <p className="text-[10px] text-gray-500 mt-0.5 font-mono break-all">{selected.id}</p>}
        {!selected && value && <p className="text-[10px] text-gray-500 mt-0.5 font-mono break-all">{value}</p>}
        {desc && <p className="text-[10px] text-gray-500 mt-0.5">{desc}</p>}
      </div>
    )
  }

  const pickFile = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.exe'
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (file) {
        navigator.clipboard.writeText(file.name).catch(() => {})
        toast(`Archivo: ${file.name} — pega la ruta completa manualmente`, { duration: 4000 })
      }
    }
    input.click()
  }

  if (!config) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-gray-400">Cargando configuracion...</p>
      </div>
    )
  }

  const g = config.global

  const input = (label: string, value: string, onChange: (v: string) => void, opts?: { type?: string; placeholder?: string; desc?: string; eye?: string }) => (
    <div>
      <label className="text-xs text-gray-400 block mb-1">{label}</label>
      <div className="flex gap-1">
        <input
          type={opts?.eye && !showPasswords.has(opts.eye) ? 'password' : (opts?.type || 'text')}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={opts?.placeholder}
          className="input flex-1"
        />
        {opts?.eye && (
          <button
            type="button"
            onClick={() => setShowPasswords((prev) => { const s = new Set(prev); s.has(opts.eye!) ? s.delete(opts.eye!) : s.add(opts.eye!); return s })}
            className="px-2 rounded-lg border border-gray-600 hover:border-brand text-gray-400 hover:text-brand text-xs transition-colors"
          >
            {showPasswords.has(opts.eye) ? '🙈' : '👁'}
          </button>
        )}
      </div>
      {opts?.desc && <p className="text-[10px] text-gray-600 mt-0.5">{opts.desc}</p>}
    </div>
  )

  const num = (label: string, value: number, onChange: (v: number) => void, desc?: string) => (
    <div>
      <label className="text-xs text-gray-400 block mb-1">{label}</label>
      <input
        type="number"
        step="any"
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className="input"
      />
      {desc && <p className="text-[10px] text-gray-600 mt-0.5">{desc}</p>}
    </div>
  )

  const toggle = (label: string, value: boolean, onChange: (v: boolean) => void) => (
    <label className="flex items-center justify-between py-2 cursor-pointer">
      <span className="text-sm text-gray-300">{label}</span>
      <input type="checkbox" checked={value} onChange={() => onChange(!value)} className="sr-only" />
      <span className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${value ? 'bg-brand' : 'bg-gray-600'}`}>
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${value ? 'translate-x-[18px]' : 'translate-x-[2px]'}`} />
      </span>
    </label>
  )

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Configuracion</h1>
        <button onClick={save} disabled={saving} className="btn-primary">
          {saving ? 'Guardando...' : 'Guardar'}
        </button>
      </div>

      {/* ── Global ── */}
      <div className="card">
        <h2 className="text-lg font-semibold mb-4">Telegram</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {input('API ID', g.telegram_api_id, (v) => updateGlobal('telegram_api_id', v), { placeholder: '123456', desc: 'my.telegram.org → API tools' })}
          {input('API Hash', g.telegram_api_hash, (v) => updateGlobal('telegram_api_hash', v), { desc: 'my.telegram.org → API tools', eye: 'api_hash' })}
          {input('Telefono', g.telegram_phone, (v) => updateGlobal('telegram_phone', v), { placeholder: '+34600000000', desc: 'Con prefijo internacional' })}
        </div>
      </div>

      {/* ── Canales ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Canales</h2>
          <button onClick={() => setShowChannelModal(true)} className="btn-outline text-xs">
            Gestionar canales
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {channelCombo('Canal de senales', g.signal_channel, (v) => updateGlobal('signal_channel', v), 'De donde se leen las senales')}
          {channelCombo('Chat de control', g.control_chat_id, (v) => updateGlobal('control_chat_id', v), 'Donde se envian comandos /help')}
          <div>
            <label className={`text-xs block mb-1 ${!g.forward_chat_id ? 'text-red-400' : 'text-gray-400'}`}>Chat de reenvio</label>
            <div className="flex gap-1">
              <select
                value={g.forward_chat_id}
                onChange={(e) => updateGlobal('forward_chat_id', e.target.value)}
                className={`input flex-1 bg-surface-dark ${!g.forward_chat_id ? 'border-red-500/50 focus:border-red-400' : ''}`}
              >
                <option value="">-- Seleccionar --</option>
                {(g.saved_channels || []).map((ch, i) => (
                  <option key={i} value={ch.id}>{ch.name}</option>
                ))}
              </select>
              <button
                onClick={testForward}
                disabled={testingForward || !g.forward_chat_id}
                className="px-2 py-2 rounded-lg border border-gray-600 hover:border-brand text-gray-400 hover:text-brand text-xs transition-colors disabled:opacity-50 whitespace-nowrap"
              >
                {testingForward ? '...' : 'Test'}
              </button>
            </div>
            {(() => {
              const sel = (g.saved_channels || []).find((ch) => ch.id === g.forward_chat_id)
              if (sel) return <p className="text-[10px] text-gray-500 mt-0.5 font-mono break-all">{sel.id}</p>
              if (g.forward_chat_id) return <p className="text-[10px] text-gray-500 mt-0.5 font-mono break-all">{g.forward_chat_id}</p>
              return null
            })()}
            <p className="text-[10px] text-gray-500 mt-0.5">Donde se reenvian resumenes</p>
          </div>
        </div>
      </div>

      {/* ── Avanzado (colapsable) ── */}
      <div className="card">
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center justify-between w-full text-left"
        >
          <h2 className="text-lg font-semibold">Avanzado</h2>
          <span className="text-gray-400 text-sm">{showAdvanced ? '▲' : '▼'}</span>
        </button>
        {showAdvanced && (
          <div className="mt-4 space-y-4">
            {toggle('Modo seco (DRY_RUN)', g.dry_run, (v) => updateGlobal('dry_run', v))}
            <p className="text-[10px] text-gray-600 -mt-1">Activado = no ejecuta en MT5, solo simula</p>
            {toggle('Confirmar trades', g.confirm_trades, (v) => updateGlobal('confirm_trades', v))}
            <p className="text-[10px] text-gray-600 -mt-1">Pedir confirmacion antes de ejecutar</p>
            <div>
              <h3 className="text-sm font-semibold text-gray-400 mb-2">Polling</h3>
              <div className="grid grid-cols-2 gap-3">
                {num('Intervalo (s)', g.polling_interval, (v) => updateGlobal('polling_interval', v))}
                {num('Mensajes por ciclo', g.message_limit, (v) => updateGlobal('message_limit', v))}
              </div>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-400 mb-2">Actualizaciones</h3>
              <div className="grid grid-cols-2 gap-3">
                {input('GitHub Repo', g.github_repo, (v) => updateGlobal('github_repo', v), { placeholder: 'usuario/repo' })}
                {input('Rama', g.github_branch, (v) => updateGlobal('github_branch', v), { placeholder: 'main' })}
              </div>
            </div>
          </div>
        )}
      </div>
      {/* ── Cuentas MT5 ── */}
      <div className="space-y-3">
        <h2 className="text-xl font-bold">Cuentas MT5</h2>

        {config.accounts.map((acc, i) => {
          const isCollapsed = collapsed.has(i)
          return (
            <div key={acc.id} className="card">
              <div className="flex items-center justify-between">
                <button
                  onClick={() => setCollapsed((prev) => { const s = new Set(prev); s.has(i) ? s.delete(i) : s.add(i); return s })}
                  className="flex items-center gap-3 text-left"
                >
                  <span className="text-gray-400 text-xs">{isCollapsed ? '▶' : '▼'}</span>
                  <h3 className="font-semibold">{acc.name || `Cuenta ${i + 1}`}</h3>
                  <span className={`text-xs px-2 py-0.5 rounded ${acc.enabled ? 'badge-green' : 'badge-red'}`}>
                    {acc.enabled ? 'Activada' : 'Desactivada'}
                  </span>
                </button>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => testAccount(acc)}
                    disabled={testing === acc.id || !acc.enabled}
                    className="text-xs text-brand hover:text-brand-light border border-brand/40 hover:border-brand px-2 py-1 rounded transition-colors disabled:opacity-50"
                  >
                    {testing === acc.id ? 'Testeando...' : 'Test'}
                  </button>
                </div>
              </div>

              {!isCollapsed && (
                <div className="mt-4 space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {input('Nombre', acc.name, (v) => updateAccount(i, 'name', v), { placeholder: 'Cuenta ' + (i+1), desc: 'Nombre visible en Dashboard' })}
                    {toggle('Cuenta activa', acc.enabled, (v) => updateAccount(i, 'enabled', v))}
                  </div>

                  <h4 className="text-sm font-semibold text-gray-400 border-t border-gray-700 pt-3">Credenciales MT5</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {input('Login', acc.login, (v) => updateAccount(i, 'login', v), { desc: 'Numero de cuenta MT5' })}
                    {input('Password', acc.password, (v) => updateAccount(i, 'password', v), { desc: 'Contrasena de MT5', eye: `mt5_pwd_${i}` })}
                    {input('Servidor', acc.server, (v) => updateAccount(i, 'server', v), { placeholder: 'Broker-Demo', desc: 'Nombre exacto del servidor' })}

                    <div>
                      <label className="text-xs text-gray-400 block mb-1">Terminal Path</label>
                      <div className="flex gap-1">
                        <input
                          type="text"
                          value={acc.terminal_path}
                          onChange={(e) => updateAccount(i, 'terminal_path', e.target.value)}
                          placeholder="C:\...\terminal64.exe"
                          className="input flex-1"
                        />
                        <button
                          type="button"
                          onClick={() => pickFile()}
                          className="px-2 py-2 rounded-lg border border-gray-600 hover:border-brand text-gray-400 hover:text-brand text-xs transition-colors whitespace-nowrap"
                          title="Buscar terminal64.exe"
                        >
                          ...
                        </button>
                      </div>
                    </div>
                  </div>

                  <h4 className="text-sm font-semibold text-gray-400 border-t border-gray-700 pt-3">Gestion de riesgo</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {num('Risk %', acc.risk_percent, (v) => updateAccount(i, 'risk_percent', v), '% del balance por operacion')}
                    {num('Max Lot', acc.max_lot_size, (v) => updateAccount(i, 'max_lot_size', v), 'Lote maximo permitido')}
                    {num('Min Lot', acc.min_lot_size, (v) => updateAccount(i, 'min_lot_size', v), 'Lote minimo permitido')}
                    {input('Magic Number', acc.default_magic, (v) => updateAccount(i, 'default_magic', v), { desc: 'ID unico para ordenes del bot' })}
                    {input('Comentario', acc.order_comment, (v) => updateAccount(i, 'order_comment', v), { desc: 'Texto en ordenes MT5' })}
                  </div>

                  <h4 className="text-sm font-semibold text-gray-400 border-t border-gray-700 pt-3">Limites diarios (0 = sin limite)</h4>
                  <div className="grid grid-cols-2 gap-3">
                    {num('Profit limite diario', acc.daily_profit_limit, (v) => updateAccount(i, 'daily_profit_limit', v), 'Pausa la cuenta al alcanzarlo')}
                    {num('Perdida limite diario', acc.daily_loss_limit, (v) => updateAccount(i, 'daily_loss_limit', v), 'Pausa la cuenta al alcanzarlo')}
                  </div>

                  <h4 className="text-sm font-semibold text-gray-400 border-t border-gray-700 pt-3">Ajustes de trading</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {num('Random offset (ticks)', acc.random_offset_ticks, (v) => updateAccount(i, 'random_offset_ticks', v), '0=off. Anti group-trading')}
                    {num('RR Ratio (0=off)', acc.rr_ratio, (v) => updateAccount(i, 'rr_ratio', v), 'Ratio riesgo/beneficio')}
                    {num('TP Index (0=ultimo)', acc.tp_index, (v) => updateAccount(i, 'tp_index', v), '1=TP1, 2=TP2, 3=TP3')}
                    {num('Reintentos orden', acc.order_retry_count, (v) => updateAccount(i, 'order_retry_count', v), '0=sin reintentos')}
                    {num('Delay reintento (s)', acc.order_retry_delay, (v) => updateAccount(i, 'order_retry_delay', v), 'Segundos entre reintentos')}
                  </div>
                  {toggle('Anti-reverse (no operar contra posicion)', acc.anti_reverse, (v) => updateAccount(i, 'anti_reverse', v))}
                  <p className="text-[10px] text-gray-600 -mt-1">Si hay una posicion o orden pendiente contraria, ignora la señal</p>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="pb-8">
        <button onClick={save} disabled={saving} className="btn-primary w-full">
          {saving ? 'Guardando...' : 'Guardar configuracion'}
        </button>
      </div>

      {/* Modal canales */}
      {showChannelModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowChannelModal(false)}>
          <div className="bg-surface rounded-xl border border-gray-600 p-6 w-full max-w-xl shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Canales guardados</h2>
              <button onClick={() => setShowChannelModal(false)} className="text-gray-400 hover:text-gray-200">✕</button>
            </div>

            <div className="flex gap-2 mb-4">
              <input type="text" value={chModalId} onChange={(e) => setChModalId(e.target.value)}
                placeholder="ID (ej: -1003954414414)" className="input flex-[2] font-mono" />
              <input type="text" value={chModalName} onChange={(e) => setChModalName(e.target.value)}
                placeholder="Nombre" className="input flex-1" />
              <button
                onClick={() => {
                  if (!chModalId || !chModalName) { toast.error('Rellena ID y nombre'); return }
                  updateGlobal('saved_channels', [...(g.saved_channels || []), { id: chModalId, name: chModalName }])
                  setChModalId(''); setChModalName('')
                }}
                className="btn-outline text-xs whitespace-nowrap"
              >+ Anadir</button>
            </div>

            <div className="space-y-1 max-h-64 overflow-auto">
              {(g.saved_channels || []).length === 0 ? (
                <p className="text-gray-500 text-xs py-4 text-center">No hay canales guardados</p>
              ) : (
                (g.saved_channels || []).map((ch, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs bg-surface-dark rounded px-3 py-1.5">
                    <span className="text-gray-300 font-mono flex-1 break-all">{ch.id}</span>
                    <span className="text-gray-400">{ch.name}</span>
                    <button onClick={() => {
                      const channels = [...(g.saved_channels || [])]
                      channels.splice(i, 1)
                      updateGlobal('saved_channels', channels)
                    }} className="text-red-400 hover:text-red-300">✕</button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
