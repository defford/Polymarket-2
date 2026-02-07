import { useState, useEffect } from 'react'
import { Clock, TrendingUp, DollarSign, Calendar, ChevronRight, ArrowLeft } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import StatsCards from './StatsCards'
import TradeHistory from './TradeHistory'
import TradeDetailModal from './TradeDetailModal'

function formatDateTime(ts) {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toLocaleString('en-US', { 
      month: 'short', day: 'numeric', 
      hour: '2-digit', minute: '2-digit', hour12: false 
    })
  } catch {
    return '—'
  }
}

function formatDuration(start, end) {
  if (!start) return '—'
  try {
    const s = new Date(start)
    const e = end ? new Date(end) : new Date()
    const diff = Math.abs(e - s) / 1000
    
    const hours = Math.floor(diff / 3600)
    const minutes = Math.floor((diff % 3600) / 60)
    
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m`
  } catch {
    return '—'
  }
}

function formatPnl(value) {
  if (value == null) return '—'
  const num = Number(value)
  const sign = num >= 0 ? '+' : ''
  return `${sign}$${num.toFixed(2)}`
}

export default function SessionsPanel() {
  const { get } = useApi()
  const [sessions, setSessions] = useState([])
  const [selectedSessionId, setSelectedSessionId] = useState(null)
  const [sessionDetails, setSessionDetails] = useState(null)
  const [loading, setLoading] = useState(false)
  const [selectedTrade, setSelectedTrade] = useState(null)

  // Fetch list of sessions
  useEffect(() => {
    get('/api/sessions').then(data => {
      if (data) setSessions(data)
    })
  }, [get])

  // Fetch details when a session is selected
  useEffect(() => {
    if (selectedSessionId) {
      setLoading(true)
      get(`/api/sessions/${selectedSessionId}`).then(data => {
        setSessionDetails(data)
        setLoading(false)
      })
    } else {
      setSessionDetails(null)
    }
  }, [selectedSessionId, get])

  if (selectedSessionId && sessionDetails) {
    // Construct a pseudo-state object for StatsCards
    const fakeState = {
      daily_pnl: sessionDetails.stats.total_pnl,
      total_pnl: sessionDetails.stats.total_pnl,
      daily_stats: sessionDetails.stats,
      consecutive_losses: 0,
      open_positions: [],
      status: sessionDetails.session.status === 'running' ? 'active' : 'stopped'
    }

    return (
      <div className="space-y-4 animate-fade-in">
        <div className="flex items-center gap-4 mb-4">
          <button 
            onClick={() => setSelectedSessionId(null)}
            className="p-2 hover:bg-surface-2 rounded-lg text-text-secondary transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h2 className="text-lg font-display font-bold">
              Session #{sessionDetails.session.id}
            </h2>
            <div className="flex items-center gap-3 text-xs text-text-dim font-mono">
              <span>{formatDateTime(sessionDetails.session.start_time)}</span>
              <span>•</span>
              <span>{formatDuration(sessionDetails.session.start_time, sessionDetails.session.end_time)}</span>
              <span>•</span>
              <span className={sessionDetails.session.status === 'completed' ? 'text-accent-green' : 'text-accent-yellow'}>
                {sessionDetails.session.status?.toUpperCase()}
              </span>
            </div>
          </div>
        </div>

        <StatsCards state={fakeState} />
        <TradeHistory trades={sessionDetails.trades} onTradeClick={setSelectedTrade} />
        {selectedTrade && (
          <TradeDetailModal
            trade={selectedTrade}
            onClose={() => setSelectedTrade(null)}
          />
        )}
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Past Sessions</span>
        <span className="text-2xs font-mono text-text-dim">{sessions.length} sessions</span>
      </div>
      
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-surface-3">
              <th className="px-4 py-2.5 text-2xs font-mono font-medium uppercase tracking-wider text-text-dim">ID</th>
              <th className="px-4 py-2.5 text-2xs font-mono font-medium uppercase tracking-wider text-text-dim">Start Time</th>
              <th className="px-4 py-2.5 text-2xs font-mono font-medium uppercase tracking-wider text-text-dim">Duration</th>
              <th className="px-4 py-2.5 text-2xs font-mono font-medium uppercase tracking-wider text-text-dim">Status</th>
              <th className="px-4 py-2.5 text-2xs font-mono font-medium uppercase tracking-wider text-text-dim">P&L</th>
              <th className="px-4 py-2.5 text-2xs font-mono font-medium uppercase tracking-wider text-text-dim"></th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((session, i) => {
              const pnl = session.total_pnl || 0
              return (
                <tr 
                  key={session.id}
                  onClick={() => setSelectedSessionId(session.id)}
                  className="border-b border-surface-2 hover:bg-surface-2/50 transition-colors cursor-pointer"
                  style={{ animationDelay: `${i * 30}ms` }}
                >
                  <td className="px-4 py-3 text-xs font-mono text-text-dim">
                    #{session.id}
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-text-primary">
                    {formatDateTime(session.start_time)}
                  </td>
                  <td className="px-4 py-3 text-xs font-mono text-text-secondary">
                    {formatDuration(session.start_time, session.end_time)}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-2xs font-mono uppercase px-2 py-1 rounded-full ${
                      session.status === 'running' ? 'bg-accent-yellow/10 text-accent-yellow' :
                      session.status === 'completed' ? 'bg-accent-green/10 text-accent-green' :
                      'bg-surface-3 text-text-dim'
                    }`}>
                      {session.status}
                    </span>
                  </td>
                  <td className={`px-4 py-3 text-xs font-mono font-medium ${
                    pnl >= 0 ? 'pnl-positive' : 'pnl-negative'
                  }`}>
                    {formatPnl(pnl)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <ChevronRight className="w-4 h-4 text-text-dim inline-block" />
                  </td>
                </tr>
              )
            })}
            {sessions.length === 0 && (
              <tr>
                <td colSpan="6" className="py-12 text-center text-text-dim">
                  <Calendar className="w-6 h-6 mx-auto mb-2 text-surface-4" />
                  No sessions found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
