import { useMemo } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { TrendingUp } from 'lucide-react'

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-surface-2 border border-surface-4 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-2xs font-mono text-text-dim mb-1">{d.time}</p>
      <p className={`text-sm font-mono font-bold tabular-nums ${
        d.cumPnl >= 0 ? 'text-accent-green' : 'text-accent-red'
      }`}>
        {d.cumPnl >= 0 ? '+' : ''}${d.cumPnl.toFixed(2)}
      </p>
      {d.tradePnl != null && (
        <p className="text-2xs font-mono text-text-dim mt-0.5">
          Trade: {d.tradePnl >= 0 ? '+' : ''}${d.tradePnl.toFixed(2)} ({d.side?.toUpperCase()})
        </p>
      )}
    </div>
  )
}

export default function PnlChart({ trades }) {
  const chartData = useMemo(() => {
    if (!trades || trades.length === 0) return []

    // Sort trades by timestamp (oldest first) and compute cumulative P&L
    const sorted = [...trades]
      .filter(t => t.status === 'filled' && t.pnl != null)
      .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))

    let cumPnl = 0
    return sorted.map((t) => {
      cumPnl += (t.pnl || 0)
      let timeStr = ''
      try {
        const d = new Date(t.timestamp)
        timeStr = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
      } catch {
        timeStr = '??:??'
      }
      return {
        time: timeStr,
        cumPnl: Number(cumPnl.toFixed(2)),
        tradePnl: t.pnl,
        side: t.side,
      }
    })
  }, [trades])

  const hasData = chartData.length > 0
  const finalPnl = hasData ? chartData[chartData.length - 1].cumPnl : 0
  const isPositive = finalPnl >= 0

  return (
    <div className="card">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-3.5 h-3.5 text-text-dim" />
          <span className="card-title">Equity Curve</span>
        </div>
        {hasData && (
          <span className={`text-sm font-mono font-bold tabular-nums ${
            isPositive ? 'pnl-positive' : 'pnl-negative'
          }`}>
            {isPositive ? '+' : ''}${finalPnl.toFixed(2)}
          </span>
        )}
      </div>
      <div className="card-body">
        {hasData ? (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="pnlGradientPos" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#00e676" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#00e676" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="pnlGradientNeg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ff1744" stopOpacity={0} />
                  <stop offset="100%" stopColor="#ff1744" stopOpacity={0.25} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#222230" vertical={false} />
              <XAxis
                dataKey="time"
                tick={{ fill: '#6b7280', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                axisLine={{ stroke: '#222230' }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: '#6b7280', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => `$${v}`}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={0} stroke="#444" strokeDasharray="2 2" />
              <Area
                type="monotone"
                dataKey="cumPnl"
                stroke={isPositive ? '#00e676' : '#ff1744'}
                strokeWidth={2}
                fill={isPositive ? 'url(#pnlGradientPos)' : 'url(#pnlGradientNeg)'}
                dot={false}
                activeDot={{
                  r: 4,
                  fill: isPositive ? '#00e676' : '#ff1744',
                  strokeWidth: 0,
                }}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[220px] flex items-center justify-center">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-surface-2 flex items-center justify-center">
                <TrendingUp className="w-6 h-6 text-surface-4" />
              </div>
              <p className="text-sm text-text-dim">No trade data yet</p>
              <p className="text-2xs text-text-dim mt-1">Chart appears after first resolved trade</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
