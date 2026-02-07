import { ArrowUpCircle, ArrowDownCircle, FlaskConical, Zap, ChevronRight } from 'lucide-react'

function formatTime(ts) {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
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

export default function TradeHistory({ trades, onTradeClick }) {
  const list = trades || []

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Trade History</span>
        <span className="text-2xs font-mono text-text-dim">{list.length} trades</span>
      </div>
      <div className="overflow-x-auto">
        {list.length > 0 ? (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-surface-3">
                {['Time', 'Side', 'Price', 'Size', 'Cost', 'P&L', 'Signal', 'Status', ...(onTradeClick ? [''] : [])].map((h, i) => (
                  <th key={h || `empty-${i}`} className="px-4 py-2.5 text-2xs font-mono font-medium uppercase tracking-wider text-text-dim">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map((trade, i) => {
                const isUp = trade.side === 'up'
                const pnl = trade.pnl
                const hasPnl = pnl != null
                const isDry = trade.is_dry_run

                return (
                  <tr
                    key={trade.id || i}
                    className={`border-b border-surface-2 hover:bg-surface-2/50 transition-colors ${onTradeClick ? 'cursor-pointer' : ''}`}
                    onClick={() => onTradeClick?.(trade)}
                    style={{ animationDelay: `${i * 30}ms` }}
                  >
                    <td className="px-4 py-2.5 text-xs font-mono text-text-secondary tabular-nums">
                      {formatTime(trade.timestamp)}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex items-center gap-1 text-xs font-mono font-medium ${
                        isUp ? 'text-accent-green' : 'text-accent-red'
                      }`}>
                        {isUp
                          ? <ArrowUpCircle className="w-3.5 h-3.5" />
                          : <ArrowDownCircle className="w-3.5 h-3.5" />
                        }
                        {trade.side?.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs font-mono text-text-primary tabular-nums">
                      ¢{((trade.price || 0) * 100).toFixed(1)}
                    </td>
                    <td className="px-4 py-2.5 text-xs font-mono text-text-secondary tabular-nums">
                      {(trade.size || 0).toFixed(2)}
                    </td>
                    <td className="px-4 py-2.5 text-xs font-mono text-text-primary tabular-nums">
                      ${(trade.cost || 0).toFixed(2)}
                    </td>
                    <td className={`px-4 py-2.5 text-xs font-mono font-medium tabular-nums ${
                      hasPnl ? (pnl >= 0 ? 'pnl-positive' : 'pnl-negative') : 'text-text-dim'
                    }`}>
                      {hasPnl ? formatPnl(pnl) : '…'}
                    </td>
                    <td className="px-4 py-2.5 text-xs font-mono text-text-dim tabular-nums">
                      {(trade.signal_score || 0) > 0 ? '+' : ''}{(trade.signal_score || 0).toFixed(2)}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-1.5">
                        {isDry && <FlaskConical className="w-3 h-3 text-accent-yellow" />}
                        <span className={`text-2xs font-mono uppercase ${
                          trade.status === 'filled' ? 'text-accent-green' :
                          trade.status === 'rejected' ? 'text-accent-red' :
                          'text-text-dim'
                        }`}>
                          {trade.status || '—'}
                        </span>
                      </div>
                    </td>
                    {onTradeClick && (
                      <td className="px-4 py-2.5 text-right">
                        <ChevronRight className="w-4 h-4 text-text-dim inline-block" />
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <div className="py-12 text-center">
            <Zap className="w-6 h-6 text-surface-4 mx-auto mb-2" />
            <p className="text-sm text-text-dim">No trades yet</p>
            <p className="text-2xs text-text-dim mt-1">Start the bot to begin trading</p>
          </div>
        )}
      </div>
    </div>
  )
}
