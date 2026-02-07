import { TrendingUp, TrendingDown, Activity, Target, DollarSign, BarChart3 } from 'lucide-react'

function formatPnl(value) {
  if (value == null) return '$0.00'
  const num = Number(value)
  const sign = num >= 0 ? '+' : ''
  return `${sign}$${num.toFixed(2)}`
}

function StatCard({ icon: Icon, label, value, subValue, color, iconColor }) {
  return (
    <div className="card animate-slide-up">
      <div className="card-body flex items-start justify-between">
        <div>
          <p className="stat-label">{label}</p>
          <p className={`stat-value mt-1 ${color || ''}`}>{value}</p>
          {subValue && (
            <p className="text-2xs font-mono text-text-dim mt-1">{subValue}</p>
          )}
        </div>
        <div className={`p-2 rounded-lg bg-surface-2 ${iconColor || 'text-text-dim'}`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
    </div>
  )
}

export default function StatsCards({ state }) {
  const dailyPnl = state.daily_pnl ?? 0
  const totalPnl = state.total_pnl ?? 0
  const stats = state.daily_stats || {}
  const winRate = stats.win_rate != null ? (stats.win_rate * 100).toFixed(0) : '—'
  const totalTrades = stats.total_trades ?? 0
  const consLosses = state.consecutive_losses ?? 0

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      <StatCard
        icon={DollarSign}
        label="Daily P&L"
        value={formatPnl(dailyPnl)}
        color={dailyPnl >= 0 ? 'pnl-positive' : 'pnl-negative'}
        iconColor={dailyPnl >= 0 ? 'text-accent-green' : 'text-accent-red'}
      />
      <StatCard
        icon={TrendingUp}
        label="Total P&L"
        value={formatPnl(totalPnl)}
        color={totalPnl >= 0 ? 'pnl-positive' : 'pnl-negative'}
        iconColor={totalPnl >= 0 ? 'text-accent-green' : 'text-accent-red'}
      />
      <StatCard
        icon={Target}
        label="Win Rate"
        value={`${winRate}%`}
        subValue={`${stats.winning_trades ?? 0}W / ${stats.losing_trades ?? 0}L`}
        iconColor="text-accent-blue"
      />
      <StatCard
        icon={BarChart3}
        label="Trades Today"
        value={totalTrades}
        iconColor="text-accent-cyan"
      />
      <StatCard
        icon={TrendingDown}
        label="Streak"
        value={consLosses > 0 ? `${consLosses} losses` : 'Clean'}
        color={consLosses >= 3 ? 'pnl-negative' : consLosses > 0 ? 'text-accent-yellow' : 'pnl-positive'}
        iconColor={consLosses >= 3 ? 'text-accent-red' : 'text-text-dim'}
      />
      <StatCard
        icon={Activity}
        label="Positions"
        value={state.open_positions?.length ?? 0}
        subValue={state.status === 'cooldown' ? 'COOLDOWN' : 'active'}
        iconColor="text-accent-yellow"
      />
    </div>
  )
}
