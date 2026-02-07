import { Activity, Wifi, WifiOff, Play, Square, Zap } from 'lucide-react'

const STATUS_CONFIG = {
  running: { label: 'LIVE', color: 'badge-green', glow: 'glow-green' },
  dry_run: { label: 'DRY RUN', color: 'badge-yellow', glow: '' },
  stopped: { label: 'STOPPED', color: 'badge-muted', glow: '' },
  error: { label: 'ERROR', color: 'badge-red', glow: 'glow-red' },
  cooldown: { label: 'COOLDOWN', color: 'badge-blue', glow: 'glow-blue' },
}

export default function StatusBar({ status, mode, connected, onStart, onStop }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.stopped
  const isRunning = status === 'running' || status === 'dry_run'

  return (
    <header className="bg-surface-1 border-b border-surface-3 px-4 py-2.5">
      <div className="max-w-[1600px] mx-auto flex items-center justify-between">
        {/* Left: Logo + Status */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-accent-cyan" />
            <h1 className="font-display text-sm font-bold tracking-wider text-text-primary uppercase">
              PM<span className="text-accent-cyan">Bot</span>
            </h1>
          </div>

          <div className="h-4 w-px bg-surface-3" />

          <span className={`${cfg.color} ${cfg.glow}`}>
            {isRunning && (
              <span className="relative flex h-1.5 w-1.5 mr-1">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-current" />
              </span>
            )}
            {cfg.label}
          </span>

          {mode === 'dry_run' && status !== 'stopped' && (
            <span className="text-2xs text-text-dim font-mono">SIMULATED</span>
          )}
        </div>

        {/* Right: Connection + Controls */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            {connected ? (
              <Wifi className="w-3.5 h-3.5 text-accent-green" />
            ) : (
              <WifiOff className="w-3.5 h-3.5 text-accent-red" />
            )}
            <span className="text-2xs font-mono text-text-dim">
              {connected ? 'CONNECTED' : 'DISCONNECTED'}
            </span>
          </div>

          <div className="h-4 w-px bg-surface-3" />

          {isRunning ? (
            <button onClick={onStop} className="btn-red text-xs py-1.5 px-3 flex items-center gap-1.5">
              <Square className="w-3 h-3" />
              Stop
            </button>
          ) : (
            <button onClick={onStart} className="btn-green text-xs py-1.5 px-3 flex items-center gap-1.5">
              <Play className="w-3 h-3" />
              Start
            </button>
          )}
        </div>
      </div>
    </header>
  )
}
