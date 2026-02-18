import { useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceDot, Legend,
} from 'recharts'
import { TrendingUp, Loader2 } from 'lucide-react'

function formatPrice(value) {
  return `¢${(value * 100).toFixed(0)}`
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  
  const upData = payload.find(p => p.dataKey === 'up_price')
  const downData = payload.find(p => p.dataKey === 'down_price')
  
  return (
    <div className="bg-surface-2 border border-surface-4 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-2xs font-mono text-text-dim mb-1">Minute {label}</p>
      {upData && (
        <p className="text-xs font-mono text-accent-green">
          Up: {formatPrice(upData.value)}
        </p>
      )}
      {downData && (
        <p className="text-xs font-mono text-accent-red">
          Down: {formatPrice(downData.value)}
        </p>
      )}
    </div>
  )
}

function CustomLegend() {
  return (
    <div className="flex items-center justify-center gap-6 mt-2">
      <div className="flex items-center gap-1.5">
        <div className="w-3 h-0.5 bg-accent-green rounded" />
        <span className="text-2xs font-mono text-text-dim">Up Token</span>
      </div>
      <div className="flex items-center gap-1.5">
        <div className="w-3 h-0.5 bg-accent-red rounded" />
        <span className="text-2xs font-mono text-text-dim">Down Token</span>
      </div>
    </div>
  )
}

export default function PriceHistoryChart({ data, tradeSide, loading }) {
  const hasIntraWindowData = data?.has_intra_window_data
  
  const chartData = useMemo(() => {
    if (!data?.available || !data.up_prices || !data.down_prices) return []
    
    return data.up_prices.map((up, i) => ({
      minute: up.minute,
      up_price: up.price,
      down_price: data.down_prices[i]?.price ?? (1 - up.price),
    }))
  }, [data])

  const entryMinute = data?.entry_minute
  const entryPrice = data?.entry_price
  const exitMinute = data?.exit_minute
  const exitPrice = data?.exit_price
  const isUp = tradeSide === 'up'
  
  const entryPriceKey = isUp ? 'up_price' : 'down_price'
  const exitPriceKey = isUp ? 'up_price' : 'down_price'

  if (loading) {
    return (
      <div className="h-[220px] flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-6 h-6 text-accent-cyan mx-auto mb-2 animate-spin" />
          <p className="text-sm text-text-dim">Loading price history...</p>
        </div>
      </div>
    )
  }

  if (!data?.available) {
    return (
      <div className="h-[220px] flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 mx-auto mb-2 rounded-full bg-surface-2 flex items-center justify-center">
            <TrendingUp className="w-5 h-5 text-surface-4" />
          </div>
          <p className="text-sm text-text-dim">Price history unavailable</p>
          {data?.reason && (
            <p className="text-2xs text-text-dim mt-1">{data.reason}</p>
          )}
        </div>
      </div>
    )
  }

  if (!hasIntraWindowData) {
    const entryUp = data?.up_prices?.find(p => p.minute === entryMinute)?.price
    const entryDown = data?.down_prices?.find(p => p.minute === entryMinute)?.price
    const exitUp = data?.up_prices?.find(p => p.minute === exitMinute && p.minute !== entryMinute)?.price
    const exitDown = data?.down_prices?.find(p => p.minute === exitMinute && p.minute !== entryMinute)?.price
    
    return (
      <div className="w-full">
        <div className="bg-surface-2 rounded-lg p-4 mb-3">
          <p className="text-xs text-text-dim text-center">
            Polymarket price history API only provides hourly data points, not minute-by-minute data.
            Showing entry and exit points from trade logs.
          </p>
        </div>
        
        <div className="grid grid-cols-2 gap-4 mb-3">
          <div className="bg-surface-2 rounded-lg p-3">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2.5 h-2.5 rounded-full bg-white border-2" style={{ borderColor: isUp ? '#00e676' : '#ff1744' }} />
              <span className="text-xs font-mono font-medium text-text-secondary">Entry</span>
            </div>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-2xs text-text-dim">Minute</span>
                <span className="text-xs font-mono text-text-primary">{entryMinute}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-2xs text-text-dim">Up Token</span>
                <span className="text-xs font-mono text-accent-green">{formatPrice(entryUp)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-2xs text-text-dim">Down Token</span>
                <span className="text-xs font-mono text-accent-red">{formatPrice(entryDown)}</span>
              </div>
            </div>
          </div>
          
          <div className="bg-surface-2 rounded-lg p-3">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2.5 h-2.5 rounded-full bg-white border-2 border-dashed" style={{ borderColor: isUp ? '#00e676' : '#ff1744' }} />
              <span className="text-xs font-mono font-medium text-text-secondary">
                {exitMinute != null && exitPrice != null ? 'Exit' : 'Resolution'}
              </span>
            </div>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-2xs text-text-dim">Minute</span>
                <span className="text-xs font-mono text-text-primary">
                  {exitMinute != null ? exitMinute : '—'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-2xs text-text-dim">Up Token</span>
                <span className="text-xs font-mono text-accent-green">{formatPrice(exitUp)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-2xs text-text-dim">Down Token</span>
                <span className="text-xs font-mono text-accent-red">{formatPrice(exitDown)}</span>
              </div>
            </div>
          </div>
        </div>
        
        <div className="bg-surface-2 rounded-lg p-3">
          <div className="flex justify-between items-center">
            <span className="text-xs font-mono text-text-dim">
              {isUp ? 'UP' : 'DOWN'} Position
            </span>
            <span className={`text-sm font-mono font-bold ${entryPrice < (exitPrice ?? 0) ? 'text-accent-green' : 'text-accent-red'}`}>
              {formatPrice(entryPrice)} → {exitPrice != null ? formatPrice(exitPrice) : '—'}
            </span>
          </div>
        </div>
      </div>
    )
  }

  if (chartData.length === 0) {
    return (
      <div className="h-[220px] flex items-center justify-center">
        <p className="text-sm text-text-dim">No price data available</p>
      </div>
    )
  }

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={200}>
        <LineChart
          data={chartData}
          margin={{ top: 10, right: 10, left: -10, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#222230" vertical={false} />
          <XAxis
            dataKey="minute"
            tick={{ fill: '#6b7280', fontSize: 10, fontFamily: 'JetBrains Mono' }}
            axisLine={{ stroke: '#222230' }}
            tickLine={false}
            label={{ value: 'Minute', position: 'bottom', fill: '#6b7280', fontSize: 10, fontFamily: 'JetBrains Mono' }}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fill: '#6b7280', fontSize: 10, fontFamily: 'JetBrains Mono' }}
            axisLine={false}
            tickLine={false}
            tickFormatter={formatPrice}
          />
          <Tooltip content={<CustomTooltip />} />
          <Line
            type="monotone"
            dataKey="up_price"
            stroke="#00e676"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#00e676', strokeWidth: 0 }}
          />
          <Line
            type="monotone"
            dataKey="down_price"
            stroke="#ff1744"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#ff1744', strokeWidth: 0 }}
          />
          {entryMinute != null && entryPrice != null && (
            <ReferenceDot
              x={entryMinute}
              y={entryPrice}
              r={6}
              fill={isUp ? '#00e676' : '#ff1744'}
              stroke="#fff"
              strokeWidth={2}
            />
          )}
          {exitMinute != null && exitPrice != null && (
            <ReferenceDot
              x={exitMinute}
              y={exitPrice}
              r={6}
              fill={isUp ? '#00e676' : '#ff1744'}
              stroke="#fff"
              strokeWidth={2}
              strokeDasharray="2 2"
            />
          )}
        </LineChart>
      </ResponsiveContainer>
      <CustomLegend />
      <div className="flex justify-center gap-6 mt-3">
        {entryMinute != null && (
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full bg-white border-2" style={{ borderColor: isUp ? '#00e676' : '#ff1744' }} />
            <span className="text-2xs font-mono text-text-dim">Entry (min {entryMinute})</span>
          </div>
        )}
        {exitMinute != null && (
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full bg-white border-2 border-dashed" style={{ borderColor: isUp ? '#00e676' : '#ff1744' }} />
            <span className="text-2xs font-mono text-text-dim">Exit (min {exitMinute})</span>
          </div>
        )}
        {exitMinute == null && entryMinute != null && (
          <div className="flex items-center gap-1.5">
            <span className="text-2xs font-mono text-text-dim italic">Position still open or market close</span>
          </div>
        )}
      </div>
    </div>
  )
}
