import { useState } from 'react'
import { X, Zap } from 'lucide-react'
import { useApi } from '../hooks/useApi'

export default function AddSimpleBotModal({ onClose, onCreated }) {
  const { post } = useApi()
  const [name, setName] = useState('')
  const [buySide, setBuySide] = useState('up')
  const [buyPrice, setBuyPrice] = useState('0.50')
  const [sellPrice, setSellPrice] = useState('0.75')
  const [sizeUsd, setSizeUsd] = useState('5')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const handleCreate = async () => {
    if (!name.trim()) {
      setError('Name is required')
      return
    }

    const buyPriceNum = parseFloat(buyPrice)
    const sellPriceNum = parseFloat(sellPrice)
    const sizeUsdNum = parseFloat(sizeUsd)

    if (isNaN(buyPriceNum) || buyPriceNum < 0.01 || buyPriceNum > 0.99) {
      setError('Buy price must be between 0.01 and 0.99')
      return
    }

    if (isNaN(sellPriceNum) || sellPriceNum < 0.01 || sellPriceNum > 0.99) {
      setError('Sell price must be between 0.01 and 0.99')
      return
    }

    if (buyPriceNum >= sellPriceNum) {
      setError('Buy price must be less than sell price')
      return
    }

    if (isNaN(sizeUsdNum) || sizeUsdNum <= 0) {
      setError('Size must be greater than 0')
      return
    }

    setCreating(true)
    setError('')

    const result = await post('/api/simple-bot', {
      name: name.trim(),
      buy_side: buySide,
      buy_price: buyPriceNum,
      sell_price: sellPriceNum,
      size_usd: sizeUsdNum,
    })

    setCreating(false)

    if (result?.bot_id) {
      onCreated?.(result.bot_id)
      onClose()
    } else if (result?.detail) {
      setError(result.detail)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="card w-full max-w-md mx-4">
        <div className="card-header">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-accent-cyan" />
            <span className="card-title">Add Simple Bot</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-3 text-text-dim hover:text-text-secondary transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="card-body space-y-4">
          <p className="text-xs text-text-dim">
            Simple bots execute basic limit order rules with no configuration.
            They buy at one price and sell at another, repeating until stopped.
          </p>

          <div>
            <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. UP 50→75"
              className="w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm font-mono text-text-primary placeholder-text-dim focus:outline-none focus:border-accent-cyan/50"
              autoFocus
            />
          </div>

          <div>
            <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
              Side
            </label>
            <div className="flex gap-2">
              <button
                onClick={() => setBuySide('up')}
                className={`flex-1 py-2 px-3 rounded-lg text-sm font-mono font-bold transition-all ${
                  buySide === 'up'
                    ? 'bg-accent-green/20 text-accent-green border border-accent-green/30'
                    : 'bg-surface-2 text-text-dim border border-surface-3 hover:border-accent-green/30'
                }`}
              >
                UP
              </button>
              <button
                onClick={() => setBuySide('down')}
                className={`flex-1 py-2 px-3 rounded-lg text-sm font-mono font-bold transition-all ${
                  buySide === 'down'
                    ? 'bg-accent-red/20 text-accent-red border border-accent-red/30'
                    : 'bg-surface-2 text-text-dim border border-surface-3 hover:border-accent-red/30'
                }`}
              >
                DOWN
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
                Buy Price (¢)
              </label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                max="0.99"
                value={buyPrice}
                onChange={e => setBuyPrice(e.target.value)}
                placeholder="0.50"
                className="w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm font-mono text-text-primary placeholder-text-dim focus:outline-none focus:border-accent-cyan/50"
              />
            </div>
            <div>
              <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
                Sell Price (¢)
              </label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                max="0.99"
                value={sellPrice}
                onChange={e => setSellPrice(e.target.value)}
                placeholder="0.75"
                className="w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm font-mono text-text-primary placeholder-text-dim focus:outline-none focus:border-accent-cyan/50"
              />
            </div>
          </div>

          <div>
            <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
              Size (USD)
            </label>
            <input
              type="number"
              step="0.5"
              min="1"
              value={sizeUsd}
              onChange={e => setSizeUsd(e.target.value)}
              placeholder="5.00"
              className="w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm font-mono text-text-primary placeholder-text-dim focus:outline-none focus:border-accent-cyan/50"
            />
          </div>

          {error && (
            <div className="text-xs text-accent-red bg-accent-red/10 border border-accent-red/20 rounded px-3 py-2">
              {error}
            </div>
          )}

          <div className="bg-surface-2 rounded-lg px-3 py-2 text-xs text-text-dim">
            <strong className="text-text-secondary">Preview:</strong>{' '}
            Buy {buySide.toUpperCase()} at {Math.round(parseFloat(buyPrice || 0) * 100)}¢, 
            sell at {Math.round(parseFloat(sellPrice || 0) * 100)}¢, 
            size ${parseFloat(sizeUsd || 0).toFixed(2)}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-xs font-mono text-text-dim hover:text-text-secondary transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={!name.trim() || creating}
              className="btn-cyan text-xs py-2 px-4 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {creating ? 'Creating...' : 'Create Simple Bot'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
