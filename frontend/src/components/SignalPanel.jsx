import { ArrowUp, ArrowDown, Minus, Layers, BarChart2, TrendingUp, FlaskConical } from 'lucide-react'

function SignalBar({ value, label, maxLabel }) {
  // value from -1 to +1
  const normalized = ((value || 0) + 1) / 2 // 0 to 1
  const pct = (normalized * 100).toFixed(0)
  const isPositive = (value || 0) > 0.05
  const isNegative = (value || 0) < -0.05

  return (
    <div>
      <div className="flex justify-between mb-1">
        <span className="data-label">{label}</span>
        <span className={`text-xs font-mono font-medium tabular-nums ${
          isPositive ? 'text-accent-green' : isNegative ? 'text-accent-red' : 'text-text-dim'
        }`}>
          {(value || 0) > 0 ? '+' : ''}{(value || 0).toFixed(3)}
        </span>
      </div>
      <div className="h-2 bg-surface-3 rounded-full overflow-hidden relative">
        {/* Center marker */}
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-surface-0/50 z-10" />
        {/* Bar */}
        <div
          className="absolute top-0 bottom-0 rounded-full transition-all duration-500"
          style={{
            left: value >= 0 ? '50%' : `${pct}%`,
            right: value >= 0 ? `${100 - pct}%` : '50%',
            backgroundColor: isPositive ? '#00e676' : isNegative ? '#ff1744' : '#6b7280',
            opacity: Math.max(0.4, Math.abs(value || 0)),
          }}
        />
      </div>
    </div>
  )
}

function TfSignalRow({ tf, value }) {
  const isUp = (value || 0) > 0.1
  const isDown = (value || 0) < -0.1

  return (
    <div className="flex items-center gap-2 py-1">
      <span className="text-2xs font-mono text-text-dim w-8">{tf}</span>
      <div className="flex-1 h-1.5 bg-surface-3 rounded-full overflow-hidden relative">
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-surface-0/50" />
        <div
          className="absolute top-0 bottom-0 rounded-full transition-all duration-700"
          style={{
            left: value >= 0 ? '50%' : `${((value + 1) / 2) * 100}%`,
            right: value >= 0 ? `${100 - ((value + 1) / 2) * 100}%` : '50%',
            backgroundColor: isUp ? '#00e676' : isDown ? '#ff1744' : '#6b7280',
            opacity: Math.max(0.3, Math.abs(value || 0)),
          }}
        />
      </div>
      <span className={`text-2xs font-mono w-6 text-right tabular-nums ${
        isUp ? 'text-accent-green' : isDown ? 'text-accent-red' : 'text-text-dim'
      }`}>
        {isUp ? '↑' : isDown ? '↓' : '—'}
      </span>
    </div>
  )
}

export default function SignalPanel({ signal }) {
  if (!signal) {
    return (
      <div className="card">
        <div className="card-header">
          <span className="card-title">Signals</span>
        </div>
        <div className="card-body py-8 text-center">
          <p className="text-sm text-text-dim">Waiting for signals…</p>
        </div>
      </div>
    )
  }

  const { layer1, layer2, composite_score, recommended_side, should_trade } = signal
  const isUp = recommended_side === 'up'
  const isDown = recommended_side === 'down'

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Signals</span>
        {should_trade ? (
          <span className={isUp ? 'badge-green' : 'badge-red'}>
            {isUp ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
            {recommended_side?.toUpperCase()}
          </span>
        ) : (
          <span className="badge-muted">
            <Minus className="w-3 h-3" /> NO TRADE
          </span>
        )}
      </div>
      <div className="card-body space-y-5">
        {/* Composite Score */}
        <div className={`p-4 rounded-lg border transition-colors ${
          should_trade
            ? isUp ? 'bg-accent-green/5 border-accent-green/20' : 'bg-accent-red/5 border-accent-red/20'
            : 'bg-surface-2 border-surface-3'
        }`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-2xs font-mono text-text-dim uppercase tracking-wider">Composite Score</span>
            <span className={`font-mono text-2xl font-bold tabular-nums ${
              should_trade
                ? isUp ? 'text-accent-green' : 'text-accent-red'
                : 'text-text-secondary'
            }`}>
              {composite_score > 0 ? '+' : ''}{(composite_score || 0).toFixed(3)}
            </span>
          </div>
          <div className="h-3 bg-surface-3 rounded-full overflow-hidden relative">
            <div className="absolute left-1/2 top-0 bottom-0 w-0.5 bg-surface-0 z-10" />
            <div
              className="absolute top-0 bottom-0 rounded-full transition-all duration-700"
              style={{
                left: composite_score >= 0 ? '50%' : `${((composite_score + 1) / 2) * 100}%`,
                right: composite_score >= 0 ? `${100 - ((composite_score + 1) / 2) * 100}%` : '50%',
                backgroundColor: (composite_score || 0) > 0 ? '#00e676' : '#ff1744',
                opacity: Math.max(0.5, Math.abs(composite_score || 0)),
              }}
            />
          </div>
        </div>

        {/* Layer 1: Polymarket TA */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <BarChart2 className="w-3.5 h-3.5 text-accent-blue" />
            <span className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider">
              Layer 1 — Token TA
            </span>
            <span className="text-2xs font-mono text-text-dim ml-auto">
              conf: {((layer1?.confidence || 0) * 100).toFixed(0)}%
            </span>
          </div>
          <div className="space-y-3 pl-1">
            <SignalBar value={layer1?.direction} label="Direction" />
            <div className="grid grid-cols-3 gap-2">
              <div className="bg-surface-2 rounded p-2 text-center">
                <p className="text-2xs text-text-dim">RSI</p>
                <p className="font-mono text-sm font-medium tabular-nums text-text-primary">
                  {layer1?.rsi != null ? layer1.rsi.toFixed(1) : '—'}
                </p>
              </div>
              <div className="bg-surface-2 rounded p-2 text-center">
                <p className="text-2xs text-text-dim">MACD</p>
                <p className="font-mono text-sm font-medium tabular-nums text-text-primary">
                  {layer1?.macd != null ? layer1.macd.toFixed(4) : '—'}
                </p>
              </div>
              <div className="bg-surface-2 rounded p-2 text-center">
                <p className="text-2xs text-text-dim">MTM</p>
                <p className="font-mono text-sm font-medium tabular-nums text-text-primary">
                  {layer1?.momentum != null ? (layer1.momentum > 0 ? '+' : '') + layer1.momentum.toFixed(4) : '—'}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Layer 2: BTC EMAs */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-3.5 h-3.5 text-accent-cyan" />
            <span className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider">
              Layer 2 — BTC EMAs
            </span>
            <span className="text-2xs font-mono text-text-dim ml-auto">
              {layer2?.alignment_count || 0}/{layer2?.total_timeframes || 6} aligned
            </span>
          </div>
          <div className="space-y-3 pl-1">
            <SignalBar value={layer2?.direction} label="Direction" />
            <div className="space-y-0.5">
              {layer2?.timeframe_signals && Object.entries(layer2.timeframe_signals).map(([tf, val]) => (
                <TfSignalRow key={tf} tf={tf} value={val} />
              ))}
              {(!layer2?.timeframe_signals || Object.keys(layer2.timeframe_signals).length === 0) && (
                <p className="text-2xs text-text-dim text-center py-2">Waiting for data…</p>
              )}
            </div>
          </div>
        </div>

        {/* VWAP & VROC — Experimental Indicators */}
        {(signal.vwap_value != null || signal.vroc_value != null) && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <FlaskConical className="w-3.5 h-3.5 text-accent-purple" />
              <span className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider">
                Experimental
              </span>
            </div>
            <div className="space-y-2 pl-1">
              {/* VWAP row */}
              <div className="grid grid-cols-2 gap-2">
                <div className={`rounded p-2 ${signal.vwap_enabled ? 'bg-accent-purple/10 border border-accent-purple/20' : 'bg-surface-2'}`}>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-2xs text-text-dim">VWAP</p>
                    <span className={`text-2xs font-mono ${signal.vwap_enabled ? 'text-accent-purple' : 'text-text-dim'}`}>
                      {signal.vwap_enabled ? 'ON' : 'off'}
                    </span>
                  </div>
                  <p className="font-mono text-sm font-medium tabular-nums text-text-primary">
                    {signal.vwap_value != null ? `$${signal.vwap_value.toFixed(0)}` : '—'}
                  </p>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-2xs text-text-dim">Signal</span>
                    <span className={`text-2xs font-mono tabular-nums ${
                      (signal.vwap_signal || 0) > 0.05 ? 'text-accent-green' :
                      (signal.vwap_signal || 0) < -0.05 ? 'text-accent-red' : 'text-text-dim'
                    }`}>
                      {(signal.vwap_signal || 0) > 0 ? '+' : ''}{(signal.vwap_signal || 0).toFixed(3)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-0.5">
                    <span className="text-2xs text-text-dim">Z-score</span>
                    <span className="text-2xs font-mono tabular-nums text-text-secondary">
                      {(signal.vwap_band_position || 0).toFixed(2)}σ
                    </span>
                  </div>
                </div>

                {/* VROC row */}
                <div className={`rounded p-2 ${signal.vroc_enabled ? 'bg-accent-purple/10 border border-accent-purple/20' : 'bg-surface-2'}`}>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-2xs text-text-dim">VROC</p>
                    <span className={`text-2xs font-mono ${signal.vroc_enabled ? 'text-accent-purple' : 'text-text-dim'}`}>
                      {signal.vroc_enabled ? 'ON' : 'off'}
                    </span>
                  </div>
                  <p className={`font-mono text-sm font-medium tabular-nums ${
                    signal.vroc_confirmed ? 'text-accent-green' : signal.vroc_enabled ? 'text-accent-red' : 'text-text-primary'
                  }`}>
                    {(signal.vroc_value || 0).toFixed(1)}%
                  </p>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-2xs text-text-dim">Status</span>
                    <span className={`text-2xs font-mono ${
                      signal.vroc_confirmed ? 'text-accent-green' : 'text-accent-red'
                    }`}>
                      {signal.vroc_confirmed ? 'Confirmed' : 'Low Vol'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
