import { Clock, ArrowUpCircle, ArrowDownCircle } from 'lucide-react'
import { useState, useEffect } from 'react'

export default function MarketPanel({ market }) {
  const [timeLeft, setTimeLeft] = useState(null)

  useEffect(() => {
    if (!market?.end_time) {
      setTimeLeft(null)
      return
    }

    const updateTimer = () => {
      const end = new Date(market.end_time)
      const now = new Date()
      const diff = Math.max(0, Math.floor((end - now) / 1000))
      setTimeLeft(diff)
    }

    updateTimer()
    const interval = setInterval(updateTimer, 1000)
    return () => clearInterval(interval)
  }, [market?.end_time])

  const formatTime = (seconds) => {
    if (seconds == null) return '--:--'
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  const isWarning = timeLeft != null && timeLeft < 120
  const isCritical = timeLeft != null && timeLeft < 30

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Active Market</span>
        {market?.active && (
          <span className="badge-green">
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-green opacity-75" />
              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent-green" />
            </span>
            LIVE
          </span>
        )}
      </div>
      <div className="card-body space-y-3">
        {market ? (
          <>
            <p className="font-sans text-sm text-text-primary font-medium leading-relaxed">
              {market.question || 'BTC 15 Minute Up or Down'}
            </p>

            {/* Timer */}
            <div className={`flex items-center gap-2 p-3 rounded-lg transition-colors ${
              isCritical ? 'bg-accent-red/10 border border-accent-red/20' :
              isWarning ? 'bg-accent-yellow/10 border border-accent-yellow/20' :
              'bg-surface-2'
            }`}>
              <Clock className={`w-4 h-4 ${
                isCritical ? 'text-accent-red' :
                isWarning ? 'text-accent-yellow' :
                'text-text-dim'
              }`} />
              <div className="flex-1">
                <p className="text-2xs uppercase tracking-wider text-text-dim">Time Remaining</p>
                <p className={`font-mono text-xl font-bold tabular-nums ${
                  isCritical ? 'text-accent-red' :
                  isWarning ? 'text-accent-yellow' :
                  'text-text-primary'
                }`}>
                  {formatTime(timeLeft)}
                </p>
              </div>
            </div>

            {/* Token Prices */}
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-surface-2 rounded-lg p-3 text-center">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <ArrowUpCircle className="w-3.5 h-3.5 text-accent-green" />
                  <span className="text-2xs font-mono text-accent-green uppercase">Up</span>
                </div>
                <p className="font-mono text-lg font-bold text-text-primary tabular-nums">
                  {market.up_price != null ? `¢${(market.up_price * 100).toFixed(1)}` : '—'}
                </p>
              </div>
              <div className="bg-surface-2 rounded-lg p-3 text-center">
                <div className="flex items-center justify-center gap-1 mb-1">
                  <ArrowDownCircle className="w-3.5 h-3.5 text-accent-red" />
                  <span className="text-2xs font-mono text-accent-red uppercase">Down</span>
                </div>
                <p className="font-mono text-lg font-bold text-text-primary tabular-nums">
                  {market.down_price != null ? `¢${(market.down_price * 100).toFixed(1)}` : '—'}
                </p>
              </div>
            </div>

            {/* Condition ID */}
            <p className="text-2xs font-mono text-text-dim truncate">
              ID: {market.condition_id?.slice(0, 20) || '—'}…
            </p>
          </>
        ) : (
          <div className="py-8 text-center">
            <p className="text-sm text-text-dim">No active market</p>
            <p className="text-2xs text-text-dim mt-1">Start the bot to discover markets</p>
          </div>
        )}
      </div>
    </div>
  )
}
