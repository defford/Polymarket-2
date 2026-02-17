import { useState, useEffect } from 'react'
import {
  X, ArrowUpCircle, ArrowDownCircle, FlaskConical, Clock,
  DollarSign, BarChart2, TrendingUp, Shield, Settings, ChevronDown, ChevronRight,
  Loader2, LogOut
} from 'lucide-react'
import { useApi } from '../hooks/useApi'
import PriceHistoryChart from './PriceHistoryChart'

// --- Formatters ---

function formatPnl(value) {
  if (value == null) return '—'
  const num = Number(value)
  const sign = num >= 0 ? '+' : ''
  return `${sign}$${num.toFixed(2)}`
}

function formatPrice(value) {
  if (value == null) return '—'
  return `¢${(Number(value) * 100).toFixed(1)}`
}

function formatBtcPrice(value) {
  if (value == null) return '—'
  return `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDuration(seconds) {
  if (seconds == null) return '—'
  const s = Math.round(seconds)
  const min = Math.floor(s / 60)
  const sec = s % 60
  if (min > 0) return `${min}m ${sec}s`
  return `${sec}s`
}

function formatDateTime(ts) {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    })
  } catch {
    return '—'
  }
}

function formatTimeRemaining(seconds) {
  if (seconds == null) return '—'
  const min = Math.floor(seconds / 60)
  const sec = Math.round(seconds % 60)
  return `${min}:${sec.toString().padStart(2, '0')}`
}

// --- Signal visualization (mirrors SignalPanel.jsx) ---

function SignalBar({ value, label }) {
  const normalized = ((value || 0) + 1) / 2
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
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-surface-0/50 z-10" />
        <div
          className="absolute top-0 bottom-0 rounded-full"
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
          className="absolute top-0 bottom-0 rounded-full"
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

// --- Collapsible Section ---

function CollapsibleSection({ title, icon: Icon, iconColor, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="card">
      <button
        onClick={() => setOpen(!open)}
        className="card-header w-full cursor-pointer hover:bg-surface-2/50 transition-colors"
      >
        <span className="card-title flex items-center gap-2">
          {Icon && <Icon className={`w-3.5 h-3.5 ${iconColor || 'text-text-dim'}`} />}
          {title}
        </span>
        {open
          ? <ChevronDown className="w-4 h-4 text-text-dim" />
          : <ChevronRight className="w-4 h-4 text-text-dim" />
        }
      </button>
      {open && <div className="card-body">{children}</div>}
    </div>
  )
}

// --- Order Book Helpers ---

function parseOrderBook(ob) {
  if (!ob) return null
  // Handle different order book formats from the API
  const bids = ob.bids || []
  const asks = ob.asks || []

  const parseLevels = (levels) =>
    levels.map(l => ({
      price: parseFloat(l.price ?? l[0] ?? 0),
      size: parseFloat(l.size ?? l[1] ?? 0),
    }))

  const parsedBids = parseLevels(bids).sort((a, b) => b.price - a.price)
  const parsedAsks = parseLevels(asks).sort((a, b) => a.price - b.price)

  const bestBid = parsedBids[0]?.price
  const bestAsk = parsedAsks[0]?.price
  const spread = bestBid != null && bestAsk != null ? bestAsk - bestBid : null
  const bidDepth5 = parsedBids.slice(0, 5).reduce((sum, l) => sum + l.price * l.size, 0)
  const askDepth5 = parsedAsks.slice(0, 5).reduce((sum, l) => sum + l.price * l.size, 0)

  return { bestBid, bestAsk, spread, bidDepth5, askDepth5, bidCount: parsedBids.length, askCount: parsedAsks.length }
}

// --- Main Modal Component ---

export default function TradeDetailModal({ trade, onClose }) {
  const { get } = useApi()
  const [details, setDetails] = useState(null)
  const [priceHistory, setPriceHistory] = useState(null)
  const [loading, setLoading] = useState(true)
  const [priceHistoryLoading, setPriceHistoryLoading] = useState(true)
  const [viewState, setViewState] = useState('entry') // 'entry' or 'exit'

  useEffect(() => {
    if (!trade?.id) return
    setLoading(true)
    setPriceHistoryLoading(true)
    get(`/api/trades/${trade.id}/details`).then(data => {
      if (data) setDetails(data)
      setLoading(false)
    })
    get(`/api/trades/${trade.id}/price-history`).then(data => {
      if (data) setPriceHistory(data)
      setPriceHistoryLoading(false)
    })
  }, [trade?.id, get])

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Prevent body scroll while modal is open
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) onClose()
  }

  if (!trade) return null

  const isUp = trade.side === 'up'
  const logData = details?.log_data
  const hasSellState = logData?.sell_state != null
  const stateData = viewState === 'exit' && hasSellState ? logData.sell_state : logData?.buy_state

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-start justify-center pt-8 pb-8 overflow-y-auto"
      onClick={handleBackdropClick}
    >
      <div className="bg-surface-1 border border-surface-3 rounded-xl max-w-4xl w-full mx-4 shadow-2xl animate-fade-in">
        {/* Header */}
        <div className="px-5 py-4 border-b border-surface-3 flex items-center justify-between sticky top-0 bg-surface-1 rounded-t-xl z-10">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-display font-bold text-text-primary">
              Trade #{trade.id}
            </h2>
            <span className={isUp ? 'badge-green' : 'badge-red'}>
              {isUp
                ? <ArrowUpCircle className="w-3 h-3" />
                : <ArrowDownCircle className="w-3 h-3" />}
              {trade.side?.toUpperCase()}
            </span>
            {trade.is_dry_run && (
              <span className="badge-yellow">
                <FlaskConical className="w-3 h-3" /> DRY RUN
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-surface-2 rounded-lg text-text-secondary transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 space-y-4">
          {loading ? (
            <div className="py-16 text-center">
              <Loader2 className="w-6 h-6 text-accent-cyan mx-auto mb-3 animate-spin" />
              <p className="text-sm text-text-dim">Loading trade details...</p>
            </div>
          ) : !details?.has_log_data ? (
            <NoLogDataView trade={details?.trade || trade} />
          ) : (
            <>
              {/* Entry/Exit Toggle */}
              {hasSellState && (
                <div className="flex gap-1 bg-surface-2 rounded-lg p-1 w-fit">
                  <button
                    onClick={() => setViewState('entry')}
                    className={`px-4 py-1.5 rounded-md text-xs font-mono font-medium transition-colors cursor-pointer ${
                      viewState === 'entry'
                        ? 'bg-surface-0 text-accent-cyan'
                        : 'text-text-dim hover:text-text-secondary'
                    }`}
                  >
                    Entry State
                  </button>
                  <button
                    onClick={() => setViewState('exit')}
                    className={`px-4 py-1.5 rounded-md text-xs font-mono font-medium transition-colors cursor-pointer ${
                      viewState === 'exit'
                        ? 'bg-surface-0 text-accent-cyan'
                        : 'text-text-dim hover:text-text-secondary'
                    }`}
                  >
                    Exit State
                  </button>
                </div>
              )}

              {/* Section 1: Trade Performance */}
              <TradePerformanceSection trade={details.trade} logData={logData} />

              {/* Section 1.5: Exit Details */}
              {logData?.exit_reason && <ExitDetailsSection logData={logData} trade={details.trade} />}

              {/* Section 1.6: Price History Chart */}
              <CollapsibleSection title="Price History (15-Min Window)" icon={TrendingUp} iconColor="text-accent-cyan">
                <PriceHistoryChart
                  data={priceHistory}
                  tradeSide={trade.side}
                  loading={priceHistoryLoading}
                />
              </CollapsibleSection>

              {/* Section 2: Market Conditions */}
              <MarketConditionsSection stateData={stateData} viewLabel={viewState} />

              {/* Section 3: Signal Breakdown */}
              <SignalBreakdownSection stateData={stateData} viewLabel={viewState} />

              {/* Section 4: Order Book */}
              <OrderBookSection stateData={stateData} viewLabel={viewState} />

              {/* Section 5: Risk State */}
              <RiskStateSection stateData={stateData} viewLabel={viewState} />

              {/* Section 6: BTC Candles */}
              <BtcCandlesSection stateData={stateData} viewLabel={viewState} />

              {/* Section 7: Config Snapshot */}
              <ConfigSection stateData={stateData} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// --- Fallback for trades without log data ---

function NoLogDataView({ trade }) {
  const isUp = trade?.side === 'up'
  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-body text-center py-8">
          <p className="text-sm text-text-dim mb-4">
            Detailed market state data is not available for this trade.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-lg mx-auto">
            <div className="bg-surface-2 rounded-lg p-3 text-center">
              <p className="text-2xs text-text-dim">Price</p>
              <p className="font-mono text-sm font-medium text-text-primary">{formatPrice(trade?.price)}</p>
            </div>
            <div className="bg-surface-2 rounded-lg p-3 text-center">
              <p className="text-2xs text-text-dim">Size</p>
              <p className="font-mono text-sm font-medium text-text-primary">{(trade?.size || 0).toFixed(2)}</p>
            </div>
            <div className="bg-surface-2 rounded-lg p-3 text-center">
              <p className="text-2xs text-text-dim">Cost</p>
              <p className="font-mono text-sm font-medium text-text-primary">${(trade?.cost || 0).toFixed(2)}</p>
            </div>
            <div className="bg-surface-2 rounded-lg p-3 text-center">
              <p className="text-2xs text-text-dim">P&L</p>
              <p className={`font-mono text-sm font-medium ${
                trade?.pnl != null ? (trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative') : 'text-text-dim'
              }`}>{formatPnl(trade?.pnl)}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// --- Section 1: Trade Performance ---

function TradePerformanceSection({ trade, logData }) {
  const pnl = logData?.pnl ?? trade?.pnl
  const hasPnl = pnl != null
  const resolution = logData?.resolution_price
  const duration = logData?.position_held_duration_seconds

  return (
    <CollapsibleSection title="Trade Performance" icon={DollarSign} iconColor="text-accent-green">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Entry Price</p>
          <p className="font-mono text-lg font-bold text-text-primary">{formatPrice(trade?.price)}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Resolution</p>
          <p className="font-mono text-lg font-bold text-text-primary">
            {resolution != null ? formatPrice(resolution) : '—'}
          </p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">P&L</p>
          <p className={`font-mono text-lg font-bold ${
            hasPnl ? (pnl >= 0 ? 'pnl-positive' : 'pnl-negative') : 'text-text-dim'
          }`}>{formatPnl(pnl)}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Duration</p>
          <p className="font-mono text-lg font-bold text-text-primary">{formatDuration(duration)}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Cost</p>
          <p className="font-mono text-lg font-bold text-text-primary">${(trade?.cost || 0).toFixed(2)}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Size</p>
          <p className="font-mono text-lg font-bold text-text-primary">{(trade?.size || 0).toFixed(2)}</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs font-mono text-text-dim">
        <span>Order: {logData?.order_type || '—'}</span>
        <span>Position: ${logData?.position_size_usd?.toFixed(2) || trade?.cost?.toFixed(2) || '—'}</span>
        <span>Fees: ${(trade?.fees || 0).toFixed(2)}</span>
        <span>Signal: {(trade?.signal_score || 0) > 0 ? '+' : ''}{(trade?.signal_score || 0).toFixed(3)}</span>
        <span>Time: {formatDateTime(trade?.timestamp)}</span>
      </div>
    </CollapsibleSection>
  )
}

// --- Section 1.5: Exit Details ---

function ExitDetailsSection({ logData, trade }) {
  const [showDetail, setShowDetail] = useState(false)
  const exitReason = logData?.exit_reason
  const exitReasonDetail = logData?.exit_reason_detail
  const exitPrice = logData?.exit_price
  const peakPrice = logData?.peak_price
  const drawdown = logData?.drawdown_from_peak
  const timeRemaining = logData?.time_remaining_at_exit
  const entryPrice = trade?.price

  if (!exitReason) return null

  // Color-code by reason category
  const reasonColors = {
    market_close: { badge: 'badge-green', label: 'Market Close', color: 'text-accent-green' },
    trailing_stop: { badge: 'badge-yellow', label: 'Trailing Stop', color: 'text-accent-yellow' },
    hard_stop: { badge: 'badge-red', label: 'Hard Stop', color: 'text-accent-red' },
    hard_take_profit: { badge: 'badge-green', label: 'Take Profit', color: 'text-accent-green' },
    signal_reversal: { badge: 'bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/20 px-2.5 py-1 rounded-full text-2xs font-mono font-medium inline-flex items-center gap-1', label: 'Signal Reversal', color: 'text-accent-cyan' },
  }
  const rc = reasonColors[exitReason] || { badge: 'badge-muted', label: exitReason, color: 'text-text-dim' }

  // Compute entry→exit price change
  const priceChange = (exitPrice != null && entryPrice != null)
    ? ((exitPrice - entryPrice) / entryPrice * 100)
    : null

  return (
    <CollapsibleSection title="Exit Details" icon={LogOut} iconColor={rc.color}>
      <div className="space-y-4">
        {/* Exit Reason Badge */}
        <div className="flex items-center gap-3">
          <span className={rc.badge}>
            <LogOut className="w-3 h-3" />
            {rc.label}
          </span>
          {timeRemaining != null && typeof timeRemaining === 'number' && (
            <span className="text-2xs font-mono text-text-dim">
              {formatTimeRemaining(timeRemaining)} remaining
            </span>
          )}
        </div>

        {/* Exit Metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-surface-2 rounded-lg p-3 text-center">
            <p className="text-2xs text-text-dim">Entry Price</p>
            <p className="font-mono text-sm font-bold text-text-primary">{formatPrice(entryPrice)}</p>
          </div>
          <div className="bg-surface-2 rounded-lg p-3 text-center">
            <p className="text-2xs text-text-dim">Exit Price</p>
            <p className={`font-mono text-sm font-bold ${
              priceChange != null ? (priceChange >= 0 ? 'text-accent-green' : 'text-accent-red') : 'text-text-primary'
            }`}>
              {formatPrice(exitPrice)}
              {priceChange != null && (
                <span className="text-2xs ml-1">({priceChange >= 0 ? '+' : ''}{priceChange.toFixed(1)}%)</span>
              )}
            </p>
          </div>
          <div className="bg-surface-2 rounded-lg p-3 text-center">
            <p className="text-2xs text-text-dim">Peak Price</p>
            <p className="font-mono text-sm font-bold text-accent-cyan">{formatPrice(peakPrice)}</p>
          </div>
          <div className="bg-surface-2 rounded-lg p-3 text-center">
            <p className="text-2xs text-text-dim">Drawdown</p>
            <p className={`font-mono text-sm font-bold ${
              drawdown != null && drawdown > 0.1 ? 'text-accent-red' : drawdown != null && drawdown > 0.05 ? 'text-accent-yellow' : 'text-text-primary'
            }`}>
              {drawdown != null ? `${(drawdown * 100).toFixed(1)}%` : '—'}
            </p>
          </div>
        </div>

        {/* Expandable Detail */}
        {exitReasonDetail && (
          <div>
            <button
              onClick={() => setShowDetail(!showDetail)}
              className="flex items-center gap-1.5 text-2xs font-mono text-text-dim hover:text-text-secondary transition-colors cursor-pointer"
            >
              {showDetail ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              Full exit reason
            </button>
            {showDetail && (
              <div className="mt-2 bg-surface-2 rounded-lg p-3">
                <p className="text-2xs font-mono text-text-secondary break-all leading-relaxed">
                  {exitReasonDetail}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </CollapsibleSection>
  )
}

// --- Section 2: Market Conditions ---

function MarketConditionsSection({ stateData, viewLabel }) {
  if (!stateData) return null
  const market = stateData.market
  const btcPrice = stateData.btc_price
  const windowInfo = stateData.market_window_info || {}

  return (
    <CollapsibleSection title={`Market Conditions (${viewLabel})`} icon={BarChart2} iconColor="text-accent-blue">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">BTC Price</p>
          <p className="font-mono text-sm font-bold text-text-primary">{formatBtcPrice(btcPrice)}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Up Token</p>
          <p className="font-mono text-sm font-bold text-accent-green">{formatPrice(market?.up_price)}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Down Token</p>
          <p className="font-mono text-sm font-bold text-accent-red">{formatPrice(market?.down_price)}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Time Left</p>
          <p className="font-mono text-sm font-bold text-text-primary">
            {formatTimeRemaining(windowInfo.time_until_close_seconds)}
          </p>
        </div>
      </div>
      {market?.question && (
        <p className="text-2xs text-text-dim font-mono mt-3">{market.question}</p>
      )}
      {market?.end_time && (
        <p className="text-2xs text-text-dim font-mono">
          Window closes: {formatDateTime(market.end_time)}
        </p>
      )}
    </CollapsibleSection>
  )
}

// --- Section 3: Signal Breakdown ---

function SignalBreakdownSection({ stateData, viewLabel }) {
  if (!stateData?.signal) return null
  const { layer1, layer2, composite_score, composite_confidence, recommended_side, should_trade } = stateData.signal
  const isUp = recommended_side === 'up'

  return (
    <CollapsibleSection title={`Signal Breakdown (${viewLabel})`} icon={TrendingUp} iconColor="text-accent-cyan">
      {/* Composite Score */}
      <div className={`p-4 rounded-lg border mb-4 ${
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
            className="absolute top-0 bottom-0 rounded-full"
            style={{
              left: composite_score >= 0 ? '50%' : `${((composite_score + 1) / 2) * 100}%`,
              right: composite_score >= 0 ? `${100 - ((composite_score + 1) / 2) * 100}%` : '50%',
              backgroundColor: (composite_score || 0) > 0 ? '#00e676' : '#ff1744',
              opacity: Math.max(0.5, Math.abs(composite_score || 0)),
            }}
          />
        </div>
        <div className="flex justify-between mt-2 text-2xs font-mono text-text-dim">
          <span>Confidence: {((composite_confidence || 0) * 100).toFixed(1)}%</span>
          <span>Rec: {recommended_side?.toUpperCase() || 'NONE'}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Layer 1 */}
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

        {/* Layer 2 */}
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
                <p className="text-2xs text-text-dim text-center py-2">No data</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </CollapsibleSection>
  )
}

// --- Section 4: Order Book ---

function OrderBookSection({ stateData, viewLabel }) {
  if (!stateData) return null
  const upBook = parseOrderBook(stateData.orderbook_up)
  const downBook = parseOrderBook(stateData.orderbook_down)

  if (!upBook && !downBook) return null

  return (
    <CollapsibleSection title={`Order Book (${viewLabel})`} icon={BarChart2} iconColor="text-accent-yellow">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {upBook && <OrderBookCard label="Up Token" book={upBook} color="text-accent-green" />}
        {downBook && <OrderBookCard label="Down Token" book={downBook} color="text-accent-red" />}
      </div>
    </CollapsibleSection>
  )
}

function OrderBookCard({ label, book, color }) {
  return (
    <div className="bg-surface-2 rounded-lg p-3">
      <p className={`text-2xs font-mono font-medium uppercase tracking-wider mb-2 ${color}`}>{label}</p>
      <div className="space-y-1.5">
        <div className="data-row">
          <span className="data-label">Best Bid</span>
          <span className="data-value">{book.bestBid != null ? formatPrice(book.bestBid) : '—'}</span>
        </div>
        <div className="data-row">
          <span className="data-label">Best Ask</span>
          <span className="data-value">{book.bestAsk != null ? formatPrice(book.bestAsk) : '—'}</span>
        </div>
        <div className="data-row">
          <span className="data-label">Spread</span>
          <span className="data-value">
            {book.spread != null ? `¢${(book.spread * 100).toFixed(1)}` : '—'}
          </span>
        </div>
        <div className="data-row">
          <span className="data-label">Bid Depth (5)</span>
          <span className="data-value">${book.bidDepth5.toFixed(2)}</span>
        </div>
        <div className="data-row">
          <span className="data-label">Ask Depth (5)</span>
          <span className="data-value">${book.askDepth5.toFixed(2)}</span>
        </div>
        <div className="data-row">
          <span className="data-label">Levels</span>
          <span className="data-value text-text-dim">{book.bidCount}B / {book.askCount}A</span>
        </div>
      </div>
    </div>
  )
}

// --- Section 5: Risk State ---

function RiskStateSection({ stateData, viewLabel }) {
  if (!stateData?.risk_state) return null
  const rs = stateData.risk_state

  return (
    <CollapsibleSection title={`Risk State (${viewLabel})`} icon={Shield} iconColor="text-accent-red">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Daily P&L</p>
          <p className={`font-mono text-sm font-bold ${
            (rs.daily_pnl || 0) >= 0 ? 'pnl-positive' : 'pnl-negative'
          }`}>{formatPnl(rs.daily_pnl)}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Consec. Losses</p>
          <p className={`font-mono text-sm font-bold ${
            (rs.consecutive_losses || 0) >= 3 ? 'text-accent-red' : 'text-text-primary'
          }`}>{rs.consecutive_losses ?? 0}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Cooldown</p>
          <p className={`font-mono text-sm font-bold ${
            rs.is_in_cooldown ? 'text-accent-yellow' : 'text-accent-green'
          }`}>{rs.is_in_cooldown ? 'Yes' : 'No'}</p>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <p className="text-2xs text-text-dim">Position Size</p>
          <p className="font-mono text-sm font-bold text-text-primary">
            ${rs.next_position_size?.toFixed(2) ?? '—'}
          </p>
        </div>
      </div>
      {rs.trades_this_market != null && (
        <p className="text-2xs text-text-dim font-mono mt-2">
          Trades this window: {rs.trades_this_market} / {rs.max_trades_per_window ?? '—'}
        </p>
      )}
    </CollapsibleSection>
  )
}

// --- Section 6: BTC Candles ---

function BtcCandlesSection({ stateData, viewLabel }) {
  if (!stateData?.btc_candles_summary) return null
  const candles = stateData.btc_candles_summary
  const tfOrder = ['1m', '5m', '15m', '1h', '4h', '1d']
  const entries = tfOrder
    .filter(tf => candles[tf])
    .map(tf => ({ tf, ...candles[tf] }))

  if (entries.length === 0) return null

  return (
    <CollapsibleSection title={`BTC Candles (${viewLabel})`} icon={TrendingUp} iconColor="text-accent-yellow" defaultOpen={false}>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-surface-3">
              {['TF', 'Open', 'High', 'Low', 'Close', 'Volume'].map(h => (
                <th key={h} className="px-3 py-2 text-2xs font-mono font-medium uppercase tracking-wider text-text-dim">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map(c => {
              const change = c.close && c.open ? c.close - c.open : 0
              return (
                <tr key={c.tf} className="border-b border-surface-2">
                  <td className="px-3 py-2 text-xs font-mono font-medium text-text-secondary">{c.tf}</td>
                  <td className="px-3 py-2 text-xs font-mono tabular-nums text-text-primary">{formatBtcPrice(c.open)}</td>
                  <td className="px-3 py-2 text-xs font-mono tabular-nums text-accent-green">{formatBtcPrice(c.high)}</td>
                  <td className="px-3 py-2 text-xs font-mono tabular-nums text-accent-red">{formatBtcPrice(c.low)}</td>
                  <td className={`px-3 py-2 text-xs font-mono tabular-nums font-medium ${
                    change >= 0 ? 'text-accent-green' : 'text-accent-red'
                  }`}>{formatBtcPrice(c.close)}</td>
                  <td className="px-3 py-2 text-xs font-mono tabular-nums text-text-dim">
                    {c.volume != null ? Number(c.volume).toFixed(1) : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </CollapsibleSection>
  )
}

// --- Section 7: Config Snapshot ---

function ConfigSection({ stateData }) {
  if (!stateData?.config_snapshot) return null
  const config = stateData.config_snapshot

  return (
    <CollapsibleSection title="Config Snapshot" icon={Settings} iconColor="text-text-dim" defaultOpen={false}>
      <div className="space-y-3">
        {config.signal && (
          <ConfigGroup label="Signal" entries={config.signal} />
        )}
        {config.risk && (
          <ConfigGroup label="Risk" entries={config.risk} />
        )}
        {config.trading && (
          <ConfigGroup label="Trading" entries={config.trading} />
        )}
        {config.exit && (
          <ConfigGroup label="Exit" entries={config.exit} />
        )}
        {config.mode && (
          <div className="data-row">
            <span className="data-label">Mode</span>
            <span className="data-value">{config.mode}</span>
          </div>
        )}
      </div>
    </CollapsibleSection>
  )
}

function ConfigGroup({ label, entries }) {
  return (
    <div>
      <p className="text-2xs font-mono text-accent-cyan uppercase tracking-wider mb-1">{label}</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-0.5">
        {Object.entries(entries).map(([key, val]) => (
          <div key={key} className="data-row py-1">
            <span className="text-2xs text-text-dim font-mono">{key}</span>
            <span className="text-xs font-mono text-text-primary ml-2">
              {typeof val === 'number' ? (Number.isInteger(val) ? val : val.toFixed(4)) : String(val)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
