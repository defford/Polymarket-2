import { useState } from 'react'
import { X, Brain, ChevronRight, ChevronDown, Sparkles, Bot, AlertTriangle } from 'lucide-react'
import { useApi } from '../hooks/useApi'

const GOALS = [
  { value: 'balanced', label: 'Balanced', desc: 'Risk-adjusted returns' },
  { value: 'win_rate', label: 'Win Rate', desc: 'Maximize win rate' },
  { value: 'pnl', label: 'Max PnL', desc: 'Maximize total profit' },
  { value: 'risk_adjusted', label: 'Low Risk', desc: 'Capital preservation' },
]

export default function AnalysisPanel({ bots, onClose, onCreated }) {
  const { get, post } = useApi()
  const [step, setStep] = useState(1) // 1=analyze, 2=review, 3=generate, 4=create
  const [analysis, setAnalysis] = useState(null)
  const [analysisId, setAnalysisId] = useState(null)
  const [recommendation, setRecommendation] = useState(null)
  const [goal, setGoal] = useState('balanced')
  const [baseBotId, setBaseBotId] = useState('')
  const [botName, setBotName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const runAnalysis = async () => {
    setLoading(true)
    setError(null)
    const result = await post('/api/analysis/run')
    setLoading(false)
    if (result?.analysis_id) {
      setAnalysisId(result.analysis_id)
      // Fetch full analysis
      const full = await get('/api/analysis/latest')
      if (full?.analysis) {
        setAnalysis(full.analysis)
        setStep(2)
      } else {
        setError('Failed to load analysis results')
      }
    } else {
      setError(result?.detail || 'Analysis failed')
    }
  }

  const generateConfig = async () => {
    setLoading(true)
    setError(null)
    const params = new URLSearchParams({ optimization_goal: goal })
    if (analysisId) params.set('analysis_id', analysisId)
    if (baseBotId) params.set('base_config_from_bot', baseBotId)
    const result = await post(`/api/analysis/generate-config?${params}`)
    setLoading(false)
    if (result?.recommendation) {
      setRecommendation(result.recommendation)
      setBotName(result.recommendation.suggested_name || 'Optimized Bot')
      setStep(4)
    } else {
      setError(result?.detail || 'Config generation failed')
    }
  }

  const createBot = async () => {
    setLoading(true)
    setError(null)
    const result = await post('/api/analysis/create-bot', {
      config: recommendation.config,
      name: botName.trim() || 'Optimized Bot',
      description: `AI-generated (${goal}). ${(recommendation.key_changes || []).slice(0, 3).join('; ')}`,
    })
    setLoading(false)
    if (result?.bot_id) {
      onCreated?.(result.bot_id)
      onClose()
    } else {
      setError(result?.detail || 'Bot creation failed')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in overflow-y-auto py-8">
      <div className="card w-full max-w-2xl mx-4 max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="card-header">
          <div className="flex items-center gap-2">
            <Brain className="w-4 h-4 text-accent-cyan" />
            <span className="card-title">Analyze & Create Bot</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-3 text-text-dim hover:text-text-secondary transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Step Indicator */}
        <div className="flex items-center gap-1 px-4 py-2 border-b border-surface-2">
          {['Analyze', 'Review', 'Generate', 'Create'].map((label, i) => (
            <div key={label} className="flex items-center gap-1">
              <div className={`
                text-2xs font-mono px-2 py-0.5 rounded-full
                ${step > i + 1 ? 'bg-accent-green/20 text-accent-green' : step === i + 1 ? 'bg-accent-cyan/20 text-accent-cyan' : 'text-text-dim'}
              `}>
                {label}
              </div>
              {i < 3 && <ChevronRight className="w-3 h-3 text-surface-4" />}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="card-body overflow-y-auto flex-1">
          {error && (
            <div className="flex items-start gap-2 p-3 mb-4 rounded bg-red-500/10 border border-red-500/20">
              <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
              <span className="text-xs font-mono text-red-400">{error}</span>
            </div>
          )}

          {/* Step 1: Run Analysis */}
          {step === 1 && (
            <div className="space-y-4 text-center py-8">
              <Brain className="w-12 h-12 text-accent-cyan/40 mx-auto" />
              <div>
                <h3 className="text-sm font-mono text-text-primary mb-1">Trade Session Analysis</h3>
                <p className="text-xs font-mono text-text-dim">
                  Analyzes all trade sessions across every bot to find performance patterns,
                  signal effectiveness, and optimization opportunities.
                </p>
              </div>
              <button
                onClick={runAnalysis}
                disabled={loading}
                className="btn-green text-xs py-2 px-6 mx-auto"
              >
                {loading ? 'Analyzing...' : 'Run Analysis'}
              </button>
            </div>
          )}

          {/* Step 2: Review Analysis */}
          {step === 2 && analysis && (
            <div className="space-y-4">
              <AnalysisSummary data={analysis.summary} />
              <SignalBuckets data={analysis.signal_score_buckets} />
              <ExitReasons data={analysis.exit_reasons} />
              <SlippageAnalysis data={analysis.slippage} />
              <MaeMfeAnalysis data={analysis.mae_mfe} />
              <FillRateAnalysis data={analysis.fill_rate} />
              <OrderbookAnalysis data={analysis.orderbook} />
              <ThresholdAnalysis data={analysis.threshold_analysis} />
              <LayerAnalysis data={analysis.layer_weight_analysis} />
              <TimePatterns data={analysis.time_patterns} />
              <HoldDuration data={analysis.hold_duration} />
              <PerBotComparison data={analysis.per_bot} />

              <div className="flex justify-end pt-2">
                <button
                  onClick={() => setStep(3)}
                  className="btn-green text-xs py-2 px-4 flex items-center gap-1"
                >
                  Next: Generate Config
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}

          {/* Step 3: Generate Config */}
          {step === 3 && (
            <div className="space-y-4">
              <div>
                <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
                  Optimization Goal
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {GOALS.map(g => (
                    <button
                      key={g.value}
                      onClick={() => setGoal(g.value)}
                      className={`
                        p-3 rounded-lg border text-left transition-all cursor-pointer
                        ${goal === g.value
                          ? 'border-accent-cyan/50 bg-accent-cyan/10'
                          : 'border-surface-3 hover:border-surface-4 bg-surface-1'
                        }
                      `}
                    >
                      <div className="text-xs font-mono text-text-primary">{g.label}</div>
                      <div className="text-2xs font-mono text-text-dim mt-0.5">{g.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
                  Base Config From (optional)
                </label>
                <select
                  value={baseBotId}
                  onChange={e => setBaseBotId(e.target.value)}
                  className="w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm font-mono text-text-primary focus:outline-none focus:border-accent-cyan/50 cursor-pointer"
                >
                  <option value="">Default Config</option>
                  {bots.map(b => (
                    <option key={b.id} value={b.id}>
                      {b.name} (#{b.id})
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex justify-between pt-2">
                <button
                  onClick={() => setStep(2)}
                  className="px-4 py-2 text-xs font-mono text-text-dim hover:text-text-secondary transition-colors cursor-pointer"
                >
                  Back
                </button>
                <button
                  onClick={generateConfig}
                  disabled={loading}
                  className="btn-green text-xs py-2 px-4 flex items-center gap-1"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  {loading ? 'Generating with AI...' : 'Generate Config'}
                </button>
              </div>
            </div>
          )}

          {/* Step 4: Create Bot */}
          {step === 4 && recommendation && (
            <div className="space-y-4">
              {/* Confidence badge */}
              <div className="flex items-center gap-2">
                <span className={`badge-${recommendation.confidence === 'high' ? 'green' : recommendation.confidence === 'low' ? 'red' : 'yellow'}`}>
                  {recommendation.confidence} confidence
                </span>
                <span className="text-2xs font-mono text-text-dim">
                  Optimized for: {recommendation.optimization_focus}
                </span>
              </div>

              {/* Reasoning */}
              <div className="card bg-surface-1">
                <div className="card-body">
                  <div className="text-2xs font-mono text-text-dim uppercase tracking-wider mb-2">AI Reasoning</div>
                  <p className="text-xs font-mono text-text-secondary whitespace-pre-wrap leading-relaxed">
                    {recommendation.reasoning}
                  </p>
                </div>
              </div>

              {/* Key Changes */}
              {recommendation.key_changes?.length > 0 && (
                <div>
                  <div className="text-2xs font-mono text-text-dim uppercase tracking-wider mb-2">Key Changes</div>
                  <div className="space-y-1">
                    {recommendation.key_changes.map((change, i) => (
                      <div key={i} className="text-xs font-mono text-text-secondary bg-surface-1 rounded px-3 py-1.5">
                        {change}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Config Preview (collapsible) */}
              <ConfigPreview config={recommendation.config} />

              {/* Bot Name */}
              <div>
                <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
                  Bot Name
                </label>
                <input
                  type="text"
                  value={botName}
                  onChange={e => setBotName(e.target.value)}
                  className="w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm font-mono text-text-primary focus:outline-none focus:border-accent-cyan/50"
                />
              </div>

              <div className="flex justify-between pt-2">
                <button
                  onClick={() => setStep(3)}
                  className="px-4 py-2 text-xs font-mono text-text-dim hover:text-text-secondary transition-colors cursor-pointer"
                >
                  Back
                </button>
                <button
                  onClick={createBot}
                  disabled={loading || !botName.trim()}
                  className="btn-green text-xs py-2 px-4 flex items-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Bot className="w-3.5 h-3.5" />
                  {loading ? 'Creating...' : 'Create Bot'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}


// --- Sub-components ---

function AnalysisSummary({ data }) {
  if (!data) return null
  return (
    <div className="card bg-surface-1">
      <div className="card-header">
        <span className="text-2xs font-mono text-text-dim uppercase tracking-wider">Summary</span>
      </div>
      <div className="card-body grid grid-cols-2 gap-2">
        <DataPoint label="Trades" value={data.total_trades_analyzed} />
        <DataPoint label="Sessions" value={data.total_sessions_analyzed} />
        <DataPoint label="Win Rate" value={`${(data.overall_win_rate * 100).toFixed(1)}%`} />
        <DataPoint label="Total PnL" value={`$${data.overall_total_pnl?.toFixed(2)}`} color={data.overall_total_pnl >= 0 ? 'green' : 'red'} />
        <DataPoint label="Avg PnL/Trade" value={`$${data.overall_avg_pnl_per_trade?.toFixed(4)}`} color={data.overall_avg_pnl_per_trade >= 0 ? 'green' : 'red'} />
        <DataPoint label="Bots" value={data.total_bots} />
      </div>
    </div>
  )
}

function SignalBuckets({ data }) {
  if (!data || Object.keys(data).length === 0) return null
  return (
    <CollapsibleSection title="Signal Score Effectiveness">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-text-dim text-2xs">
            <th className="text-left pb-1">Score</th>
            <th className="text-right pb-1">Trades</th>
            <th className="text-right pb-1">Win Rate</th>
            <th className="text-right pb-1">Avg PnL</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).sort().map(([range, d]) => (
            <tr key={range} className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">{range}</td>
              <td className="py-1 text-right text-text-dim">{d.count}</td>
              <td className={`py-1 text-right ${d.win_rate >= 0.5 ? 'text-accent-green' : 'text-accent-red'}`}>
                {(d.win_rate * 100).toFixed(0)}%
              </td>
              <td className={`py-1 text-right ${d.avg_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                ${d.avg_pnl?.toFixed(4)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </CollapsibleSection>
  )
}

function ExitReasons({ data }) {
  if (!data || Object.keys(data).length === 0) return null
  return (
    <CollapsibleSection title="Exit Reasons">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-text-dim text-2xs">
            <th className="text-left pb-1">Reason</th>
            <th className="text-right pb-1">Count</th>
            <th className="text-right pb-1">Avg PnL</th>
            <th className="text-right pb-1">Avg Hold</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).map(([reason, d]) => (
            <tr key={reason} className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">{reason}</td>
              <td className="py-1 text-right text-text-dim">{d.count}</td>
              <td className={`py-1 text-right ${d.avg_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                ${d.avg_pnl?.toFixed(4)}
              </td>
              <td className="py-1 text-right text-text-dim">{d.avg_hold_seconds?.toFixed(0)}s</td>
            </tr>
          ))}
        </tbody>
      </table>
    </CollapsibleSection>
  )
}

function ThresholdAnalysis({ data }) {
  if (!data || Object.keys(data).length === 0) return null
  return (
    <CollapsibleSection title="Buy Threshold Effectiveness">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-text-dim text-2xs">
            <th className="text-left pb-1">Threshold</th>
            <th className="text-right pb-1">Trades</th>
            <th className="text-right pb-1">Win Rate</th>
            <th className="text-right pb-1">Avg PnL</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).sort().map(([thresh, d]) => (
            <tr key={thresh} className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">{thresh}</td>
              <td className="py-1 text-right text-text-dim">{d.trades_above}</td>
              <td className={`py-1 text-right ${d.win_rate_above >= 0.5 ? 'text-accent-green' : 'text-accent-red'}`}>
                {(d.win_rate_above * 100).toFixed(0)}%
              </td>
              <td className={`py-1 text-right ${d.avg_pnl_above >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                ${d.avg_pnl_above?.toFixed(4)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </CollapsibleSection>
  )
}

function LayerAnalysis({ data }) {
  if (!data) return null
  return (
    <CollapsibleSection title="Layer Weight Analysis">
      <div className="space-y-2 text-xs font-mono">
        {data.l1_direction_vs_pnl_correlation != null && (
          <div className="data-row">
            <span className="data-label">L1 vs PnL Correlation</span>
            <span className="data-value">{data.l1_direction_vs_pnl_correlation?.toFixed(4)}</span>
          </div>
        )}
        {data.l2_direction_vs_pnl_correlation != null && (
          <div className="data-row">
            <span className="data-label">L2 vs PnL Correlation</span>
            <span className="data-value">{data.l2_direction_vs_pnl_correlation?.toFixed(4)}</span>
          </div>
        )}
        {data.both_agree_trades?.count > 0 && (
          <div className="data-row">
            <span className="data-label">Layers Agree</span>
            <span className="data-value">
              {data.both_agree_trades.count} trades, {(data.both_agree_trades.win_rate * 100).toFixed(0)}% win
            </span>
          </div>
        )}
        {data.layers_disagree_trades?.count > 0 && (
          <div className="data-row">
            <span className="data-label">Layers Disagree</span>
            <span className="data-value">
              {data.layers_disagree_trades.count} trades, {(data.layers_disagree_trades.win_rate * 100).toFixed(0)}% win
            </span>
          </div>
        )}
      </div>
    </CollapsibleSection>
  )
}

function TimePatterns({ data }) {
  if (!data?.hourly || Object.keys(data.hourly).length === 0) return null
  return (
    <CollapsibleSection title="Time-of-Day Patterns">
      <div className="space-y-2 text-xs font-mono">
        {data.best_hours?.length > 0 && (
          <div className="data-row">
            <span className="data-label">Best Hours (UTC)</span>
            <span className="data-value text-accent-green">{data.best_hours.join(', ')}</span>
          </div>
        )}
        {data.worst_hours?.length > 0 && (
          <div className="data-row">
            <span className="data-label">Worst Hours (UTC)</span>
            <span className="data-value text-accent-red">{data.worst_hours.join(', ')}</span>
          </div>
        )}
      </div>
    </CollapsibleSection>
  )
}

function HoldDuration({ data }) {
  if (!data?.duration_buckets || Object.keys(data.duration_buckets).length === 0) return null
  return (
    <CollapsibleSection title="Hold Duration vs PnL">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-text-dim text-2xs">
            <th className="text-left pb-1">Duration</th>
            <th className="text-right pb-1">Trades</th>
            <th className="text-right pb-1">Win Rate</th>
            <th className="text-right pb-1">Avg PnL</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.duration_buckets).map(([range, d]) => (
            <tr key={range} className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">{range}</td>
              <td className="py-1 text-right text-text-dim">{d.count}</td>
              <td className={`py-1 text-right ${d.win_rate >= 0.5 ? 'text-accent-green' : 'text-accent-red'}`}>
                {(d.win_rate * 100).toFixed(0)}%
              </td>
              <td className={`py-1 text-right ${d.avg_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                ${d.avg_pnl?.toFixed(4)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </CollapsibleSection>
  )
}

function PerBotComparison({ data }) {
  if (!data || Object.keys(data).length === 0) return null
  return (
    <CollapsibleSection title="Per-Bot Comparison">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-text-dim text-2xs">
            <th className="text-left pb-1">Bot</th>
            <th className="text-right pb-1">Trades</th>
            <th className="text-right pb-1">Win Rate</th>
            <th className="text-right pb-1">Total PnL</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).map(([id, d]) => (
            <tr key={id} className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">{d.name}</td>
              <td className="py-1 text-right text-text-dim">{d.total_trades}</td>
              <td className={`py-1 text-right ${d.win_rate >= 0.5 ? 'text-accent-green' : 'text-accent-red'}`}>
                {(d.win_rate * 100).toFixed(0)}%
              </td>
              <td className={`py-1 text-right ${d.total_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                ${d.total_pnl?.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </CollapsibleSection>
  )
}

function SlippageAnalysis({ data }) {
  if (!data || !data.by_order_type || Object.keys(data.by_order_type).length === 0) return null
  return (
    <CollapsibleSection title="Slippage Analysis">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-text-dim text-2xs">
            <th className="text-left pb-1">Order Type</th>
            <th className="text-right pb-1">Trades</th>
            <th className="text-right pb-1">Entry Slip</th>
            <th className="text-right pb-1">Exit Slip</th>
            <th className="text-right pb-1">Cost</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.by_order_type).map(([type, d]) => (
            <tr key={type} className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">{type}</td>
              <td className="py-1 text-right text-text-dim">{d.count}</td>
              <td className={`py-1 text-right ${d.avg_entry_slippage_bps > 0 ? 'text-accent-red' : 'text-accent-green'}`}>
                {d.avg_entry_slippage_bps?.toFixed(1)} bps
              </td>
              <td className={`py-1 text-right ${d.avg_exit_slippage_bps < 0 ? 'text-accent-red' : 'text-accent-green'}`}>
                {d.avg_exit_slippage_bps?.toFixed(1)} bps
              </td>
              <td className="py-1 text-right text-accent-red">${d.total_slippage_cost?.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="data-row mt-2">
        <span className="data-label">Total Slippage Cost</span>
        <span className="data-value text-accent-red">${data.total_slippage_cost?.toFixed(2)}</span>
      </div>
    </CollapsibleSection>
  )
}

function MaeMfeAnalysis({ data }) {
  if (!data || (!data.winners?.count && !data.losers?.count)) return null
  return (
    <CollapsibleSection title="MAE / MFE Analysis">
      <div className="space-y-3">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-text-dim text-2xs">
              <th className="text-left pb-1">Metric</th>
              <th className="text-right pb-1">Winners</th>
              <th className="text-right pb-1">Losers</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">Count</td>
              <td className="py-1 text-right text-accent-green">{data.winners?.count || 0}</td>
              <td className="py-1 text-right text-accent-red">{data.losers?.count || 0}</td>
            </tr>
            <tr className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">Avg MAE (drawdown)</td>
              <td className="py-1 text-right text-text-dim">{((data.winners?.avg_mae_pct || 0) * 100).toFixed(2)}%</td>
              <td className="py-1 text-right text-text-dim">{((data.losers?.avg_mae_pct || 0) * 100).toFixed(2)}%</td>
            </tr>
            <tr className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">Avg MFE (max profit)</td>
              <td className="py-1 text-right text-text-dim">{((data.winners?.avg_mfe_pct || 0) * 100).toFixed(2)}%</td>
              <td className="py-1 text-right text-text-dim">{((data.losers?.avg_mfe_pct || 0) * 100).toFixed(2)}%</td>
            </tr>
          </tbody>
        </table>
        {data.winners?.avg_capture_ratio != null && (
          <div className="data-row">
            <span className="data-label">Profit Capture Ratio</span>
            <span className="data-value">{((data.winners.avg_capture_ratio || 0) * 100).toFixed(0)}%</span>
          </div>
        )}
        {data.winners?.avg_missed_profit_pct != null && (
          <div className="data-row">
            <span className="data-label">Avg Missed Profit</span>
            <span className="data-value text-accent-yellow">{((data.winners.avg_missed_profit_pct || 0) * 100).toFixed(2)}%</span>
          </div>
        )}
        {data.recovery_by_mae_threshold && Object.keys(data.recovery_by_mae_threshold).length > 0 && (
          <div>
            <div className="text-2xs font-mono text-text-dim uppercase tracking-wider mb-1 mt-2">Recovery After Drawdown</div>
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-text-dim text-2xs">
                  <th className="text-left pb-1">MAE Threshold</th>
                  <th className="text-right pb-1">Trades</th>
                  <th className="text-right pb-1">Recovery Rate</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.recovery_by_mae_threshold).map(([thresh, d]) => (
                  <tr key={thresh} className="border-t border-surface-2">
                    <td className="py-1 text-text-secondary">Dipped {thresh}+</td>
                    <td className="py-1 text-right text-text-dim">{d.total}</td>
                    <td className={`py-1 text-right ${d.recovery_rate >= 0.5 ? 'text-accent-green' : 'text-accent-red'}`}>
                      {(d.recovery_rate * 100).toFixed(0)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </CollapsibleSection>
  )
}

function FillRateAnalysis({ data }) {
  if (!data || !data.by_order_type || Object.keys(data.by_order_type).length === 0) return null
  return (
    <CollapsibleSection title="Fill Rate Analysis">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-text-dim text-2xs">
            <th className="text-left pb-1">Order Type</th>
            <th className="text-right pb-1">Attempts</th>
            <th className="text-right pb-1">Fill Rate</th>
            <th className="text-right pb-1">Avg Time</th>
            <th className="text-right pb-1">Avg PnL</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.by_order_type).map(([type, d]) => (
            <tr key={type} className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">{type}</td>
              <td className="py-1 text-right text-text-dim">{d.total_attempts}</td>
              <td className={`py-1 text-right ${d.fill_rate >= 0.9 ? 'text-accent-green' : d.fill_rate >= 0.7 ? 'text-accent-yellow' : 'text-accent-red'}`}>
                {(d.fill_rate * 100).toFixed(0)}%
              </td>
              <td className="py-1 text-right text-text-dim">{d.avg_time_to_fill?.toFixed(1)}s</td>
              <td className={`py-1 text-right ${d.avg_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                ${d.avg_pnl?.toFixed(4)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.fok_vs_limit && (
        <div className="space-y-1 mt-2">
          <div className="data-row">
            <span className="data-label">FOK Trades</span>
            <span className="data-value">{data.fok_vs_limit.fok_count} (avg ${data.fok_vs_limit.fok_avg_pnl?.toFixed(4)})</span>
          </div>
          <div className="data-row">
            <span className="data-label">Limit Trades</span>
            <span className="data-value">{data.fok_vs_limit.non_fok_count} (avg ${data.fok_vs_limit.non_fok_avg_pnl?.toFixed(4)})</span>
          </div>
        </div>
      )}
    </CollapsibleSection>
  )
}

function OrderbookAnalysis({ data }) {
  if (!data || (!data.winners?.count && !data.losers?.count)) return null
  return (
    <CollapsibleSection title="Order Book Analysis">
      <div className="space-y-3">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-text-dim text-2xs">
              <th className="text-left pb-1">Metric</th>
              <th className="text-right pb-1">Winners</th>
              <th className="text-right pb-1">Losers</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">Avg Imbalance</td>
              <td className={`py-1 text-right ${(data.winners?.avg_imbalance_at_entry || 0) > 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                {data.winners?.avg_imbalance_at_entry?.toFixed(4)}
              </td>
              <td className={`py-1 text-right ${(data.losers?.avg_imbalance_at_entry || 0) > 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                {data.losers?.avg_imbalance_at_entry?.toFixed(4)}
              </td>
            </tr>
            <tr className="border-t border-surface-2">
              <td className="py-1 text-text-secondary">Avg Spread</td>
              <td className="py-1 text-right text-text-dim">{data.winners?.avg_spread_at_entry?.toFixed(4)}</td>
              <td className="py-1 text-right text-text-dim">{data.losers?.avg_spread_at_entry?.toFixed(4)}</td>
            </tr>
          </tbody>
        </table>
        {data.imbalance_vs_pnl_correlation != null && (
          <div className="data-row">
            <span className="data-label">Imbalance vs PnL Correlation</span>
            <span className="data-value">{data.imbalance_vs_pnl_correlation?.toFixed(4)}</span>
          </div>
        )}
        {data.by_imbalance_direction && Object.keys(data.by_imbalance_direction).length > 0 && (
          <div>
            <div className="text-2xs font-mono text-text-dim uppercase tracking-wider mb-1 mt-2">By Imbalance Direction</div>
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-text-dim text-2xs">
                  <th className="text-left pb-1">Direction</th>
                  <th className="text-right pb-1">Trades</th>
                  <th className="text-right pb-1">Win Rate</th>
                  <th className="text-right pb-1">Avg PnL</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.by_imbalance_direction).map(([dir, d]) => (
                  <tr key={dir} className="border-t border-surface-2">
                    <td className="py-1 text-text-secondary">{dir.replace('_', ' ')}</td>
                    <td className="py-1 text-right text-text-dim">{d.count}</td>
                    <td className={`py-1 text-right ${d.win_rate >= 0.5 ? 'text-accent-green' : 'text-accent-red'}`}>
                      {(d.win_rate * 100).toFixed(0)}%
                    </td>
                    <td className={`py-1 text-right ${d.avg_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                      ${d.avg_pnl?.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </CollapsibleSection>
  )
}

function ConfigPreview({ config }) {
  const [open, setOpen] = useState(false)
  if (!config) return null
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-2xs font-mono text-text-dim uppercase tracking-wider hover:text-text-secondary transition-colors cursor-pointer"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        Full Config
      </button>
      {open && (
        <pre className="mt-2 p-3 bg-surface-0 rounded-lg text-2xs font-mono text-text-dim overflow-x-auto max-h-60 overflow-y-auto">
          {JSON.stringify(config, null, 2)}
        </pre>
      )}
    </div>
  )
}

function CollapsibleSection({ title, children }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="card bg-surface-1">
      <button
        onClick={() => setOpen(!open)}
        className="card-header w-full cursor-pointer hover:bg-surface-2 transition-colors"
      >
        <span className="text-2xs font-mono text-text-dim uppercase tracking-wider">{title}</span>
        {open ? <ChevronDown className="w-3.5 h-3.5 text-text-dim" /> : <ChevronRight className="w-3.5 h-3.5 text-text-dim" />}
      </button>
      {open && <div className="card-body">{children}</div>}
    </div>
  )
}

function DataPoint({ label, value, color }) {
  return (
    <div className="data-row">
      <span className="data-label">{label}</span>
      <span className={`data-value ${color === 'green' ? 'text-accent-green' : color === 'red' ? 'text-accent-red' : ''}`}>
        {value}
      </span>
    </div>
  )
}
