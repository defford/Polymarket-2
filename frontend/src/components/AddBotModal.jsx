import { useState } from 'react'
import { X } from 'lucide-react'
import { useApi } from '../hooks/useApi'

export default function AddBotModal({ bots, onClose, onCreated }) {
  const { post } = useApi()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [cloneFrom, setCloneFrom] = useState('')
  const [creating, setCreating] = useState(false)

  const handleCreate = async () => {
    if (!name.trim()) return
    setCreating(true)
    const body = {
      name: name.trim(),
      description: description.trim(),
    }
    if (cloneFrom) {
      body.clone_from = Number(cloneFrom)
    }
    const result = await post('/api/swarm', body)
    setCreating(false)
    if (result?.bot_id) {
      onCreated?.(result.bot_id)
      onClose()
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="card w-full max-w-md mx-4">
        <div className="card-header">
          <span className="card-title">Add Bot</span>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-3 text-text-dim hover:text-text-secondary transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="card-body space-y-4">
          <div>
            <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Aggressive Scalper"
              className="w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm font-mono text-text-primary placeholder-text-dim focus:outline-none focus:border-accent-cyan/50"
              autoFocus
            />
          </div>

          <div>
            <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
              Description
            </label>
            <input
              type="text"
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional description..."
              className="w-full bg-surface-0 border border-surface-3 rounded-lg px-3 py-2 text-sm font-mono text-text-primary placeholder-text-dim focus:outline-none focus:border-accent-cyan/50"
            />
          </div>

          <div>
            <label className="text-2xs font-mono text-text-dim uppercase tracking-wider block mb-1.5">
              Clone Config From
            </label>
            <select
              value={cloneFrom}
              onChange={e => setCloneFrom(e.target.value)}
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
              className="btn-green text-xs py-2 px-4 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {creating ? 'Creating...' : 'Create Bot'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
