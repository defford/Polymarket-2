import { useState, useEffect } from 'react'
import { TrendingUp, BarChart3, Target, Bot } from 'lucide-react'
import { useApi } from '../hooks/useApi'

const TIME_SCALES = [
  { key: 'hour', label: '1H' },
  { key: 'day', label: '24H' },
  { key: 'all', label: 'ALL' },
]

function formatPnl(value) {
  if (value == null) return '$0.00'
  const num = Number(value)
  const sign = num >= 0 ? '+' : ''
  return `${sign}$${num.toFixed(2)}`
}

export default function SwarmSummary() {
  const { get } = useApi()
  const [timeScale, setTimeScale] = useState('all')
  const [summary, setSummary] = useState(null)

  useEffect(() => {
    get(`/api/swarm/summary?time_scale=${timeScale}`).then(data => {
      if (data) setSummary(data)
    })
  }, [get, timeScale])

  // Refresh periodically
  useEffect(() => {
    const interval = setInterval(() => {
      get(`/api/swarm/summary?time_scale=${timeScale}`).then(data => {
        if (data) setSummary(data)
      })
    }, 15000)
    return () => clearInterval(interval)
  }, [get, timeScale])

  const stats = summary || {}

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Swarm Performance</span>
        <div className="flex gap-1">
          {TIME_SCALES.map(ts => (
            <button
              key={ts.key}
              onClick={() => setTimeScale(ts.key)}
              className={`px-2.5 py-1 text-2xs font-mono font-semibold rounded transition-colors cursor-pointer ${
                timeScale === ts.key
                  ? 'bg-accent-cyan/15 text-accent-cyan'
                  : 'text-text-dim hover:text-text-secondary hover:bg-surface-3'
              }`}
            >
              {ts.label}
            </button>
          ))}
        </div>
      </div>
      <div className="card-body">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div>
            <div className="text-2xs font-mono text-text-dim uppercase tracking-wider mb-1 flex items-center gap-1.5">
              <TrendingUp className="w-3 h-3" /> Total P&L
            </div>
            <div className={`text-lg font-mono font-bold ${
              (stats.total_pnl || 0) >= 0 ? 'pnl-positive' : 'pnl-negative'
            }`}>
              {formatPnl(stats.total_pnl)}
            </div>
          </div>

          <div>
            <div className="text-2xs font-mono text-text-dim uppercase tracking-wider mb-1 flex items-center gap-1.5">
              <Bot className="w-3 h-3" /> Active Bots
            </div>
            <div className="text-lg font-mono font-bold text-text-primary">
              {stats.active_bots || 0}<span className="text-text-dim text-sm">/{stats.total_bots || 0}</span>
            </div>
          </div>

          <div>
            <div className="text-2xs font-mono text-text-dim uppercase tracking-wider mb-1 flex items-center gap-1.5">
              <BarChart3 className="w-3 h-3" /> Total Trades
            </div>
            <div className="text-lg font-mono font-bold text-text-primary">
              {stats.total_trades || 0}
            </div>
          </div>

          <div>
            <div className="text-2xs font-mono text-text-dim uppercase tracking-wider mb-1 flex items-center gap-1.5">
              <Target className="w-3 h-3" /> Win Rate
            </div>
            <div className="text-lg font-mono font-bold text-text-primary">
              {stats.total_trades > 0
                ? `${((stats.win_rate || 0) * 100).toFixed(0)}%`
                : '—'}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
