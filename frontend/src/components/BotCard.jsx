import { Play, Square, TrendingUp, BarChart3, Target, ChevronRight, Trash2 } from 'lucide-react'
import { useApi } from '../hooks/useApi'

const STATUS_BADGES = {
  running: { label: 'LIVE', cls: 'badge-green' },
  dry_run: { label: 'DRY RUN', cls: 'badge-yellow' },
  stopped: { label: 'STOPPED', cls: 'badge-muted' },
  error: { label: 'ERROR', cls: 'badge-red' },
  cooldown: { label: 'COOLDOWN', cls: 'badge-blue' },
}

function formatPnl(value) {
  if (value == null) return '$0.00'
  const num = Number(value)
  const sign = num >= 0 ? '+' : ''
  return `${sign}$${num.toFixed(2)}`
}

export default function BotCard({ bot, wsState, onClick, onRefresh }) {
  const { post, del } = useApi()

  // Merge API list data with live WS state
  const liveState = wsState || {}
  const status = liveState.status || bot.status || 'stopped'
  const isRunning = status === 'running' || status === 'dry_run'
  const mode = liveState.mode || bot.mode || 'dry_run'
  const totalPnl = liveState.total_pnl ?? bot.total_pnl ?? 0
  const dailyPnl = liveState.daily_pnl ?? bot.daily_pnl ?? 0
  const openPositions = liveState.open_positions?.length ?? bot.open_positions ?? 0
  const totalTrades = liveState.daily_stats?.total_trades ?? bot.total_trades ?? 0
  const winRate = liveState.daily_stats?.win_rate ?? bot.win_rate ?? 0

  const badge = STATUS_BADGES[status] || STATUS_BADGES.stopped

  const handleToggle = async (e) => {
    e.stopPropagation()
    if (isRunning) {
      await post(`/api/swarm/${bot.id}/stop`)
    } else {
      await post(`/api/swarm/${bot.id}/start`)
    }
    onRefresh?.()
  }

  const handleDelete = async (e) => {
    e.stopPropagation()
    if (!window.confirm(`Delete "${bot.name}"? This cannot be undone.`)) return
    await del(`/api/swarm/${bot.id}`)
    onRefresh?.()
  }

  return (
    <div
      onClick={() => onClick?.(bot.id)}
      className="card hover:border-surface-4 transition-all cursor-pointer group"
    >
      <div className="card-body space-y-3">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-display font-bold text-text-primary truncate">
                {bot.name}
              </h3>
              <span className={badge.cls}>
                {isRunning && (
                  <span className="relative flex h-1.5 w-1.5 mr-1">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" />
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-current" />
                  </span>
                )}
                {badge.label}
              </span>
            </div>
            {bot.description && (
              <p className="text-2xs text-text-dim font-mono mt-0.5 truncate">
                {bot.description}
              </p>
            )}
          </div>
          <ChevronRight className="w-4 h-4 text-text-dim opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 mt-1" />
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-3">
          <div>
            <div className="text-2xs font-mono text-text-dim uppercase tracking-wider flex items-center gap-1">
              <TrendingUp className="w-2.5 h-2.5" /> P&L
            </div>
            <div className={`text-sm font-mono font-bold ${totalPnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`}>
              {formatPnl(totalPnl)}
            </div>
          </div>
          <div>
            <div className="text-2xs font-mono text-text-dim uppercase tracking-wider flex items-center gap-1">
              <BarChart3 className="w-2.5 h-2.5" /> Trades
            </div>
            <div className="text-sm font-mono font-bold text-text-primary">
              {totalTrades}
            </div>
          </div>
          <div>
            <div className="text-2xs font-mono text-text-dim uppercase tracking-wider flex items-center gap-1">
              <Target className="w-2.5 h-2.5" /> Win
            </div>
            <div className="text-sm font-mono font-bold text-text-primary">
              {totalTrades > 0 ? `${(winRate * 100).toFixed(0)}%` : '—'}
            </div>
          </div>
        </div>

        {/* Footer: positions + controls */}
        <div className="flex items-center justify-between pt-1 border-t border-surface-2">
          <div className="text-2xs font-mono text-text-dim">
            {openPositions > 0 ? (
              <span className="text-accent-cyan">{openPositions} open position{openPositions !== 1 ? 's' : ''}</span>
            ) : (
              'No open positions'
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={handleDelete}
              className="p-1.5 rounded-md text-text-dim hover:text-accent-red hover:bg-accent-red/10 transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
              title="Delete bot"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
            {isRunning ? (
              <button
                onClick={handleToggle}
                className="btn-red text-2xs py-1 px-2.5 flex items-center gap-1"
              >
                <Square className="w-2.5 h-2.5" /> Stop
              </button>
            ) : (
              <button
                onClick={handleToggle}
                className="btn-green text-2xs py-1 px-2.5 flex items-center gap-1"
              >
                <Play className="w-2.5 h-2.5" /> Start
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
