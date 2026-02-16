import { useState, useEffect, useCallback } from 'react'
import { Settings, Sliders, Shield, Zap, Save, RotateCcw, AlertTriangle, FlaskConical, Power } from 'lucide-react'

function Section({ icon: Icon, title, description, children, color = 'text-text-dim' }) {
  return (
    <div className="card animate-slide-up">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${color}`} />
          <span className="card-title">{title}</span>
        </div>
      </div>
      <div className="card-body space-y-4">
        {description && (
          <p className="text-xs text-text-dim leading-relaxed">{description}</p>
        )}
        {children}
      </div>
    </div>
  )
}

function SliderParam({ label, value, min, max, step, unit, onChange, description }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="data-label">{label}</label>
        <span className="text-sm font-mono font-medium text-accent-cyan tabular-nums">
          {typeof value === 'number' ? value.toFixed(step < 1 ? 2 : 0) : value}{unit || ''}
        </span>
      </div>
      {description && (
        <p className="text-2xs text-text-dim mb-2">{description}</p>
      )}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none bg-surface-3 cursor-pointer accent-accent-cyan"
      />
      <div className="flex justify-between mt-1">
        <span className="text-2xs font-mono text-text-dim">{min}{unit}</span>
        <span className="text-2xs font-mono text-text-dim">{max}{unit}</span>
      </div>
    </div>
  )
}

function NumberParam({ label, value, min, max, step, unit, onChange }) {
  return (
    <div className="flex items-center justify-between">
      <label className="data-label flex-1">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
          className="input-field w-24 text-right text-sm py-1.5"
        />
        {unit && <span className="text-2xs font-mono text-text-dim w-6">{unit}</span>}
      </div>
    </div>
  )
}

function SelectParam({ label, value, options, onChange }) {
  return (
    <div className="flex items-center justify-between">
      <label className="data-label">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="input-field w-36 text-sm py-1.5 cursor-pointer"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  )
}

function ToggleParam({ label, value, onChange, color = 'bg-accent-green' }) {
  return (
    <div className="flex items-center justify-between">
      <label className="data-label">{label}</label>
      <button
        onClick={() => onChange(!value)}
        className={`w-10 h-5 rounded-full transition-colors relative cursor-pointer ${
          value ? color : 'bg-surface-3'
        }`}
      >
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
          value ? 'translate-x-5' : 'translate-x-0.5'
        }`} />
      </button>
    </div>
  )
}

export default function ConfigPanel({ config, configEnabled, onUpdate, onToggleConfigEnabled }) {
  const [local, setLocal] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (config && !local) {
      setLocal(JSON.parse(JSON.stringify(config)))
    }
  }, [config, local])

  const update = useCallback((section, key, value) => {
    setLocal((prev) => {
      const next = { ...prev }
      if (section) {
        next[section] = { ...next[section], [key]: value }
      } else {
        next[key] = value
      }
      return next
    })
    setDirty(true)
  }, [])

  const handleSave = useCallback(async () => {
    if (!local || !onUpdate) return
    setSaving(true)
    await onUpdate(local)
    setDirty(false)
    setSaving(false)
  }, [local, onUpdate])

  const handleReset = useCallback(() => {
    if (config) {
      setLocal(JSON.parse(JSON.stringify(config)))
      setDirty(false)
    }
  }, [config])

  if (!local) {
    return (
      <div className="py-12 text-center">
        <p className="text-sm text-text-dim">Loading configuration…</p>
      </div>
    )
  }

  const sig = local.signal || {}
  const risk = local.risk || {}
  const trading = local.trading || {}

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Save Bar */}
      {dirty && (
        <div className="bg-accent-blue/10 border border-accent-blue/30 rounded-lg p-3 flex items-center justify-between sticky top-14 z-20 backdrop-blur-md">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-accent-blue" />
            <span className="text-sm text-accent-blue font-medium">Unsaved changes</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={handleReset} className="btn-ghost text-xs py-1.5">
              <RotateCcw className="w-3 h-3 mr-1 inline" />
              Reset
            </button>
            <button onClick={handleSave} disabled={saving} className="btn-primary text-xs py-1.5">
              <Save className="w-3 h-3 mr-1 inline" />
              {saving ? 'Saving…' : 'Save & Apply'}
            </button>
          </div>
        </div>
      )}

      {/* Config Toggle */}
      <div className="card animate-slide-up">
        <div className="card-header">
          <div className="flex items-center gap-2">
            <Power className={`w-4 h-4 ${configEnabled ? 'text-accent-green' : 'text-text-dim'}`} />
            <span className="card-title">Custom Config</span>
          </div>
        </div>
        <div className="card-body">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-text-secondary">
                {configEnabled ? 'Using custom configuration' : 'Using default configuration'}
              </p>
              <p className="text-2xs text-text-dim mt-1">
                {configEnabled
                  ? 'Disable to use default values while refining strategy'
                  : 'Enable to apply custom settings from this profile'}
              </p>
            </div>
            <button
              onClick={() => onToggleConfigEnabled && onToggleConfigEnabled(!configEnabled)}
              className={`w-12 h-6 rounded-full transition-colors relative cursor-pointer ${
                configEnabled ? 'bg-accent-green' : 'bg-surface-3'
              }`}
            >
              <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                configEnabled ? 'translate-x-6' : 'translate-x-0.5'
              }`} />
            </button>
          </div>
          {!configEnabled && (
            <div className="mt-3 bg-accent-yellow/10 border border-accent-yellow/20 rounded-lg p-3 flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-accent-yellow mt-0.5 shrink-0" />
              <p className="text-xs text-accent-yellow">
                Config is disabled. All parameters below show the saved profile values, but the bot is currently using default settings.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Mode */}
      <Section icon={Zap} title="Bot Mode" color="text-accent-cyan">
        <div className="flex gap-3">
          {[
            { value: 'dry_run', label: 'Dry Run', desc: 'Simulated trades, no real money' },
            { value: 'live', label: 'Live', desc: 'Real orders with real USDC' },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => update(null, 'mode', opt.value)}
              className={`flex-1 p-4 rounded-lg border-2 transition-all cursor-pointer text-left ${
                local.mode === opt.value
                  ? opt.value === 'live'
                    ? 'border-accent-red bg-accent-red/5'
                    : 'border-accent-cyan bg-accent-cyan/5'
                  : 'border-surface-3 bg-surface-2 hover:border-surface-4'
              }`}
            >
              <p className={`text-sm font-display font-semibold ${
                local.mode === opt.value
                  ? opt.value === 'live' ? 'text-accent-red' : 'text-accent-cyan'
                  : 'text-text-secondary'
              }`}>
                {opt.label}
              </p>
              <p className="text-2xs text-text-dim mt-1">{opt.desc}</p>
            </button>
          ))}
        </div>
        {local.mode === 'live' && (
          <div className="bg-accent-red/10 border border-accent-red/20 rounded-lg p-3 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-accent-red mt-0.5 shrink-0" />
            <p className="text-xs text-accent-red">
              Live mode will place real orders with real USDC. Make sure your wallet is funded and you understand the risks.
            </p>
          </div>
        )}
      </Section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Signal Config */}
        <Section
          icon={Sliders}
          title="Signal Parameters"
          description="Tune how signals are generated and combined."
          color="text-accent-blue"
        >
          <div className="space-y-5">
            <div className="pb-3 border-b border-surface-2">
              <p className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider mb-3">
                Signal Weights
              </p>
              <div className="space-y-4">
                <SliderParam
                  label="Layer 1 Weight (Token TA)"
                  value={sig.layer1_weight ?? 0.4}
                  min={0} max={1} step={0.05}
                  onChange={(v) => update('signal', 'layer1_weight', v)}
                />
                <SliderParam
                  label="Layer 2 Weight (BTC EMAs)"
                  value={sig.layer2_weight ?? 0.6}
                  min={0} max={1} step={0.05}
                  onChange={(v) => update('signal', 'layer2_weight', v)}
                />
                <SliderParam
                  label="Buy Threshold"
                  value={sig.buy_threshold ?? 0.3}
                  min={0.05} max={0.9} step={0.05}
                  description="Composite score must exceed this to trigger a trade"
                  onChange={(v) => update('signal', 'buy_threshold', v)}
                />
              </div>
            </div>

            <div className="pb-3 border-b border-surface-2">
              <p className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider mb-3">
                Layer 1: Polymarket Token TA
              </p>
              <div className="space-y-3">
                <NumberParam label="RSI Period" value={sig.pm_rsi_period ?? 14}
                  min={5} max={30} step={1} onChange={(v) => update('signal', 'pm_rsi_period', v)} />
                <NumberParam label="RSI Oversold" value={sig.pm_rsi_oversold ?? 30}
                  min={10} max={45} step={1} onChange={(v) => update('signal', 'pm_rsi_oversold', v)} />
                <NumberParam label="RSI Overbought" value={sig.pm_rsi_overbought ?? 70}
                  min={55} max={90} step={1} onChange={(v) => update('signal', 'pm_rsi_overbought', v)} />
                <NumberParam label="MACD Fast" value={sig.pm_macd_fast ?? 12}
                  min={5} max={20} step={1} onChange={(v) => update('signal', 'pm_macd_fast', v)} />
                <NumberParam label="MACD Slow" value={sig.pm_macd_slow ?? 26}
                  min={15} max={40} step={1} onChange={(v) => update('signal', 'pm_macd_slow', v)} />
                <NumberParam label="MACD Signal" value={sig.pm_macd_signal ?? 9}
                  min={3} max={15} step={1} onChange={(v) => update('signal', 'pm_macd_signal', v)} />
                <NumberParam label="Momentum Lookback" value={sig.pm_momentum_lookback ?? 5}
                  min={2} max={15} step={1} onChange={(v) => update('signal', 'pm_momentum_lookback', v)} />
              </div>
            </div>
          </div>
        </Section>

        {/* Experimental Indicators (VWAP & VROC) */}
        <Section
          icon={FlaskConical}
          title="Experimental Indicators"
          description="Toggle VWAP and VROC on/off for A/B testing. Values are always computed and logged regardless of toggle state."
          color="text-accent-purple"
        >
          <div className="space-y-5">
            {/* VWAP */}
            <div className="pb-3 border-b border-surface-2">
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider">
                  VWAP (Fair Value)
                </p>
                <ToggleParam
                  label=""
                  value={sig.vwap_enabled ?? false}
                  onChange={(v) => update('signal', 'vwap_enabled', v)}
                  color="bg-accent-purple"
                />
              </div>
              <p className="text-2xs text-text-dim mb-3">
                Volume Weighted Average Price. When enabled, blends a directional signal into the composite score based on where BTC price sits relative to the session VWAP.
              </p>
              <div className={`space-y-3 transition-opacity ${sig.vwap_enabled ? 'opacity-100' : 'opacity-40'}`}>
                <SliderParam
                  label="VWAP Weight"
                  value={sig.vwap_weight ?? 0.15}
                  min={0.05} max={0.5} step={0.05}
                  description="Blending weight (L1 + L2 + VWAP normalize to 1.0)"
                  onChange={(v) => update('signal', 'vwap_weight', v)}
                />
                <NumberParam label="Session Reset Hour (UTC)" value={sig.vwap_session_reset_hour_utc ?? 0}
                  min={0} max={23} step={1} onChange={(v) => update('signal', 'vwap_session_reset_hour_utc', v)} />
              </div>
            </div>

            {/* VROC */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider">
                  VROC (Volume Gate)
                </p>
                <ToggleParam
                  label=""
                  value={sig.vroc_enabled ?? false}
                  onChange={(v) => update('signal', 'vroc_enabled', v)}
                  color="bg-accent-purple"
                />
              </div>
              <p className="text-2xs text-text-dim mb-3">
                Volume Rate of Change. When enabled, penalises signal confidence if the current candle's volume is below the threshold vs. recent average. Filters out low-volume fakeouts.
              </p>
              <div className={`space-y-3 transition-opacity ${sig.vroc_enabled ? 'opacity-100' : 'opacity-40'}`}>
                <NumberParam label="Lookback Candles (15m)" value={sig.vroc_lookback ?? 10}
                  min={3} max={30} step={1} onChange={(v) => update('signal', 'vroc_lookback', v)} />
                <SliderParam
                  label="VROC Threshold"
                  value={sig.vroc_threshold ?? 50}
                  min={10} max={200} step={5} unit="%"
                  description="Minimum VROC% to confirm breakout volume"
                  onChange={(v) => update('signal', 'vroc_threshold', v)}
                />
                <SliderParam
                  label="Confidence Penalty"
                  value={sig.vroc_confidence_penalty ?? 0.5}
                  min={0.1} max={1.0} step={0.05}
                  description="Multiply confidence by this when VROC is below threshold"
                  onChange={(v) => update('signal', 'vroc_confidence_penalty', v)}
                />
              </div>
            </div>
          </div>
        </Section>

        {/* Risk + Trading Config */}
        <div className="space-y-4">
          <Section
            icon={Shield}
            title="Risk Management"
            description="Controls to protect your capital."
            color="text-accent-yellow"
          >
            <div className="space-y-4">
              <SliderParam
                label="Max Position Size"
                value={risk.max_position_size ?? 3}
                min={1} max={100} step={1} unit="$"
                description="Maximum USDC per trade"
                onChange={(v) => update('risk', 'max_position_size', v)}
              />
              <SliderParam
                label="Max Daily Loss"
                value={risk.max_daily_loss ?? 15}
                min={5} max={500} step={5} unit="$"
                description="Bot stops trading after this daily loss"
                onChange={(v) => update('risk', 'max_daily_loss', v)}
              />
              <SliderParam
                label="Min Signal Confidence"
                value={risk.min_signal_confidence ?? 0.6}
                min={0.1} max={1.0} step={0.05}
                description="Minimum confidence to allow a trade"
                onChange={(v) => update('risk', 'min_signal_confidence', v)}
              />
              <NumberParam label="Max Trades / Window" value={risk.max_trades_per_window ?? 1}
                min={1} max={5} step={1} onChange={(v) => update('risk', 'max_trades_per_window', v)} />
              <NumberParam label="Max Consecutive Losses" value={risk.max_consecutive_losses ?? 3}
                min={1} max={10} step={1} onChange={(v) => update('risk', 'max_consecutive_losses', v)} />
              <NumberParam label="Cooldown (minutes)" value={risk.cooldown_minutes ?? 30}
                min={5} max={120} step={5} unit="min" onChange={(v) => update('risk', 'cooldown_minutes', v)} />
              <NumberParam label="Stop Before Close" value={risk.stop_trading_minutes_before_close ?? 2}
                min={0} max={10} step={1} unit="min" onChange={(v) => update('risk', 'stop_trading_minutes_before_close', v)} />
              <SliderParam
                label="Max Entry Price"
                value={risk.max_entry_price ?? 0.8}
                min={0.1} max={0.95} step={0.05}
                description="Max price (cents) to pay for a contract"
                onChange={(v) => update('risk', 'max_entry_price', v)}
              />
            </div>
          </Section>

          <Section
            icon={Settings}
            title="Trading Behavior"
            description="How orders are placed on Polymarket."
            color="text-accent-green"
          >
            <div className="space-y-3">
              <SelectParam
                label="Order Type"
                value={trading.order_type ?? 'postOnly'}
                options={[
                  { value: 'postOnly', label: 'Post Only (maker)' },
                  { value: 'limit', label: 'Limit' },
                  { value: 'market', label: 'Market (FOK)' },
                ]}
                onChange={(v) => update('trading', 'order_type', v)}
              />
              <NumberParam label="Price Offset" value={trading.price_offset ?? 0.01}
                min={0} max={0.1} step={0.005} onChange={(v) => update('trading', 'price_offset', v)} />
              <NumberParam label="Poll Interval" value={trading.poll_interval_seconds ?? 10}
                min={3} max={60} step={1} unit="s" onChange={(v) => update('trading', 'poll_interval_seconds', v)} />
              <NumberParam label="Market Discovery Interval" value={trading.market_discovery_interval_seconds ?? 30}
                min={10} max={120} step={5} unit="s"                 onChange={(v) => update('trading', 'market_discovery_interval_seconds', v)} />

              <div className="border-t border-surface-2 pt-3">
                <ToggleParam
                  label="Use FOK for Strong Signals"
                  value={trading.use_fok_for_strong_signals}
                  onChange={(v) => update('trading', 'use_fok_for_strong_signals', v)}
                />
                {trading.use_fok_for_strong_signals && (
                  <div className="mt-2">
                    <SliderParam
                      label="Strong Signal Threshold"
                      value={trading.strong_signal_threshold ?? 0.8}
                      min={0.5} max={1.0} step={0.05}
                      onChange={(v) => update('trading', 'strong_signal_threshold', v)}
                    />
                  </div>
                )}
              </div>
            </div>
          </Section>

          <Section
            icon={RotateCcw}
            title="Exit Strategy"
            description="Trailing stops and position management."
            color="text-accent-red"
          >
            <div className="space-y-4">
              <ToggleParam
                label="Enable Exit Strategy"
                value={local.exit?.enabled ?? true}
                onChange={(v) => update('exit', 'enabled', v)}
                color="bg-accent-red"
              />

              {local.exit?.enabled && (
                <div className="space-y-3 pt-2 animate-fade-in">
                  <SliderParam
                    label="Trailing Stop %"
                    value={local.exit?.trailing_stop_pct ?? 0.2}
                    min={0.05} max={0.5} step={0.01}
                    onChange={(v) => update('exit', 'trailing_stop_pct', v)}
                  />
                  <SliderParam
                    label="Hard Stop %"
                    value={local.exit?.hard_stop_pct ?? 0.5}
                    min={0.1} max={0.9} step={0.05}
                    onChange={(v) => update('exit', 'hard_stop_pct', v)}
                  />
                  <SliderParam
                    label="Reversal Threshold"
                    value={local.exit?.signal_reversal_threshold ?? 0.15}
                    min={0.05} max={0.5} step={0.01}
                    onChange={(v) => update('exit', 'signal_reversal_threshold', v)}
                  />

                  <div className="pt-2 border-t border-surface-2">
                    <p className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider mb-3">
                      Take Profit
                    </p>
                    <div className="space-y-3">
                      <ToggleParam
                        label="Hard Take Profit"
                        value={local.exit?.hard_tp_enabled ?? false}
                        onChange={(v) => update('exit', 'hard_tp_enabled', v)}
                        color="bg-accent-green"
                      />
                      {local.exit?.hard_tp_enabled && (
                        <div className="ml-2 animate-fade-in">
                          <SliderParam
                            label="Take Profit %"
                            value={local.exit?.hard_tp_pct ?? 0.10}
                            min={0.02} max={0.50} step={0.01}
                            description="Exit when price rises this % from entry"
                            onChange={(v) => update('exit', 'hard_tp_pct', v)}
                          />
                        </div>
                      )}
                      <ToggleParam
                        label="Scaling Take Profit"
                        value={local.exit?.scaling_tp_enabled ?? false}
                        onChange={(v) => update('exit', 'scaling_tp_enabled', v)}
                        color="bg-accent-green"
                      />
                      {local.exit?.scaling_tp_enabled && (
                        <div className="ml-2 space-y-3 animate-fade-in">
                          <SliderParam
                            label="Scaling Factor"
                            value={local.exit?.scaling_tp_pct ?? 0.50}
                            min={0.10} max={1.00} step={0.05}
                            description="Fraction of unrealized gain used to tighten trailing stop"
                            onChange={(v) => update('exit', 'scaling_tp_pct', v)}
                          />
                          <SliderParam
                            label="Min Trailing Stop Floor"
                            value={local.exit?.scaling_tp_min_trail ?? 0.02}
                            min={0.005} max={0.10} step={0.005}
                            description="Trailing stop can never go below this %"
                            onChange={(v) => update('exit', 'scaling_tp_min_trail', v)}
                          />
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="pt-2 border-t border-surface-2">
                    <p className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider mb-3">
                      Time Decay
                    </p>
                    <div className="space-y-3">
                      <NumberParam label="Tighten At (sec)" value={local.exit?.tighten_at_seconds ?? 180}
                        min={60} max={600} step={10} onChange={(v) => update('exit', 'tighten_at_seconds', v)} />
                      <NumberParam label="Tightened Stop %" value={local.exit?.tightened_trailing_pct ?? 0.10}
                        min={0.01} max={0.3} step={0.01} onChange={(v) => update('exit', 'tightened_trailing_pct', v)} />
                      <NumberParam label="Final Seconds" value={local.exit?.final_seconds ?? 60}
                        min={10} max={300} step={10} onChange={(v) => update('exit', 'final_seconds', v)} />
                      <NumberParam label="Final Stop %" value={local.exit?.final_trailing_pct ?? 0.05}
                        min={0.01} max={0.2} step={0.01} onChange={(v) => update('exit', 'final_trailing_pct', v)} />
                      <NumberParam label="Min Hold (sec)" value={local.exit?.min_hold_seconds ?? 20}
                        min={0} max={120} step={5} onChange={(v) => update('exit', 'min_hold_seconds', v)} />
                    </div>
                  </div>

                  <div className="pt-2 border-t border-surface-2">
                    <ToggleParam
                      label="Survival Buffer"
                      value={local.exit?.survival_buffer_enabled ?? true}
                      onChange={(v) => update('exit', 'survival_buffer_enabled', v)}
                      color="bg-accent-yellow"
                      description="15 BPS hard stop for first 180s, no trailing"
                    />
                    {local.exit?.survival_buffer_enabled && (
                      <div className="space-y-3 mt-3 animate-fade-in">
                        <NumberParam label="Buffer Duration (sec)" value={local.exit?.survival_buffer_seconds ?? 180}
                          min={30} max={300} step={10} onChange={(v) => update('exit', 'survival_buffer_seconds', v)} />
                        <NumberParam label="Hard Stop (BPS)" value={local.exit?.survival_hard_stop_bps ?? 15}
                          min={5} max={100} step={5} onChange={(v) => update('exit', 'survival_hard_stop_bps', v)} />
                      </div>
                    )}
                  </div>

                  <div className="pt-2 border-t border-surface-2">
                    <p className="text-xs font-display font-semibold text-text-secondary uppercase tracking-wider mb-3">
                      Conviction Scaling
                    </p>
                    <div className="space-y-3">
                      <div className="text-2xs text-text-dim mb-2">
                        Adjust exits based on entry conviction (composite_confidence)
                      </div>
                      <NumberParam label="High Conviction Threshold" value={local.exit?.high_conviction_threshold ?? 0.45}
                        min={0.3} max={0.9} step={0.05} onChange={(v) => update('exit', 'high_conviction_threshold', v)} />
                      <NumberParam label="High Conviction TP %" value={local.exit?.high_conviction_tp_pct ?? 0.35}
                        min={0.1} max={0.6} step={0.05} onChange={(v) => update('exit', 'high_conviction_tp_pct', v)} />
                      <NumberParam label="Low Conviction Threshold" value={local.exit?.low_conviction_threshold ?? 0.25}
                        min={0.1} max={0.4} step={0.05} onChange={(v) => update('exit', 'low_conviction_threshold', v)} />
                      <NumberParam label="Low Conviction Trail %" value={local.exit?.low_conviction_trail_pct ?? 0.001}
                        min={0.001} max={0.05} step={0.001} onChange={(v) => update('exit', 'low_conviction_trail_pct', v)} />
                    </div>
                  </div>

                  <div className="pt-2 border-t border-surface-2">
                    <ToggleParam
                      label="Pressure Scaling (BTC)"
                      value={local.exit?.pressure_scaling_enabled ?? true}
                      onChange={(v) => update('exit', 'pressure_scaling_enabled', v)}
                      color="bg-accent-red"
                    />
                    {local.exit?.pressure_scaling_enabled && (
                      <div className="space-y-3 mt-3">
                        <NumberParam label="Max Widen Multiplier" value={local.exit?.pressure_widen_max ?? 1.5}
                          min={1.0} max={3.0} step={0.1} onChange={(v) => update('exit', 'pressure_widen_max', v)} />
                        <NumberParam label="Min Tighten Multiplier" value={local.exit?.pressure_tighten_min ?? 0.4}
                          min={0.1} max={1.0} step={0.1} onChange={(v) => update('exit', 'pressure_tighten_min', v)} />
                        <NumberParam label="Neutral Zone" value={local.exit?.pressure_neutral_zone ?? 0.15}
                          min={0.05} max={0.5} step={0.01} onChange={(v) => update('exit', 'pressure_neutral_zone', v)} />
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Section>
        </div>
      </div>
    </div>
  )
}
