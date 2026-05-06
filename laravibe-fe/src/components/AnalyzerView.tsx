import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Wrench, RefreshCw, Box, AlertCircle, X } from 'lucide-react';
import { INITIAL_PHP_CODE, MASTER_REPAIR_TOKEN } from '../constants';
import { cn } from '../lib/utils';

export const AnalyzerView: React.FC = () => {
  const navigate = useNavigate();
  const [code, setCode] = React.useState(INITIAL_PHP_CODE);
  const [prompt, setPrompt] = React.useState("");
  const [maxIterations, setMaxIterations] = React.useState(7);
  const [useBoost, setUseBoost] = React.useState(true);
  const [useMutationGate, setUseMutationGate] = React.useState(true);
  const [isLoading, setIsLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleRepair = async () => {
    setIsLoading(true);
    setError(null);
    console.info('[LaraVibe] Initiating repair request...', { 
      max_iterations: maxIterations,
      use_boost: useBoost,
      use_mutation_gate: useMutationGate,
      has_prompt: !!prompt.trim()
    });
    try {
      const sessionToken = localStorage.getItem('laravibe_session_token');
      const response = await fetch('/api/repair', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${sessionToken}`
        },
        body: JSON.stringify({ 
          code, 
          prompt: prompt.trim() || null,
          max_iterations: maxIterations,
          use_boost: useBoost,
          use_mutation_gate: useMutationGate
        })
      });
      console.info('[LaraVibe] Backend Response:', { status: response.status, ok: response.ok });
      if (!response.ok) {
        const errJson = await response.json().catch(() => ({ detail: 'Unknown error' }));
        const msg = errJson.detail || `HTTP ${response.status}`;
        throw new Error(msg);
      }
      const data = await response.json();
      console.info('[LaraVibe] Submission ID:', data.submission_id);
      navigate(`/repair/${data.submission_id}`);
    } catch (e: any) {
      console.error(e);
      setError(e?.message || 'Failed to submit repair request. Is the API server running?');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Error Banner */}
      {error && (
        <div className="shrink-0 mx-4 mt-3 flex items-start gap-3 bg-error/10 border border-error/40 text-error rounded-lg px-4 py-3 animate-fade-in">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span className="mono text-[11px] font-bold flex-1 leading-relaxed">{error}</span>
          <button onClick={() => setError(null)} className="shrink-0 hover:opacity-60 transition-opacity">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        {/* Left Panel: INPUT */}
        <section className="w-1/3 flex flex-col border-r border-outline-variant bg-surface-container-low">
          <div className="h-10 px-4 flex items-center justify-between border-b border-outline-variant bg-surface-container-high/50">
            <h2 className="text-sm font-semibold text-on-surface-variant">Input</h2>
          </div>
          <div className="flex-1 flex flex-col gap-3 overflow-auto bg-surface-container-lowest p-4 text-sm leading-relaxed text-primary/80">
            <div className="flex flex-col gap-1 shrink-0">
              <label className="text-xs font-semibold text-primary">Notes / context (optional)</label>
              <textarea 
                className="w-full h-16 bg-primary/5 border border-primary/30 rounded p-3 text-sm text-on-surface outline-none focus:border-primary focus:ring-1 focus:ring-primary/50 transition-all resize-none placeholder:text-on-surface-variant/40 custom-scrollbar"
                placeholder="Describe the problem or paste any relevant context."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                spellCheck="false"
              />
            </div>
            <div className="flex-1 flex flex-col gap-1">
              <label className="text-xs font-semibold text-sky-500">Broken code</label>
              <textarea 
                className="w-full h-full bg-sky-500/5 border border-sky-500/30 rounded p-4 outline-none resize-none font-mono text-sm text-on-surface focus:border-sky-500 focus:ring-1 focus:ring-sky-500/50 transition-all placeholder:text-on-surface-variant/30 leading-relaxed custom-scrollbar"
                placeholder={'<?php\n\n// Paste your broken Laravel code here...\n// The system will analyze errors and generate a patch.'}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                spellCheck="false"
              />
            </div>
          </div>
          <div className="h-24 px-4 flex flex-col justify-center gap-3 border-t border-outline-variant bg-surface-container-low">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <label className="text-xs font-semibold text-secondary">Max iterations</label>
                <input 
                  className="w-14 h-9 bg-secondary/5 border border-secondary/30 text-center text-sm font-mono text-on-surface rounded focus:border-secondary focus:ring-1 focus:ring-secondary/50 outline-none transition-all" 
                  type="number" 
                  min={1}
                  max={15}
                  value={maxIterations}
                  onChange={(e) => setMaxIterations(Number(e.target.value))}
                />
              </div>
              
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer text-sm text-on-surface-variant">
                  <span>Boost</span>
                  <input type="checkbox" checked={useBoost} onChange={e => setUseBoost(e.target.checked)} className="accent-primary" />
                </label>
                <label className="flex items-center gap-2 cursor-pointer text-sm text-on-surface-variant">
                  <span>Mutate</span>
                  <input type="checkbox" checked={useMutationGate} onChange={e => setUseMutationGate(e.target.checked)} className="accent-secondary" />
                </label>
              </div>
            </div>
            
            <button 
              onClick={handleRepair}
              disabled={isLoading || !code.trim()}
              className={cn(
                "w-full py-3 rounded-md text-sm font-semibold flex items-center justify-center gap-2 active:scale-[0.98] transition-all",
                isLoading || !code.trim()
                  ? "bg-surface-container-highest text-outline cursor-not-allowed"
                  : "bg-primary text-on-primary hover:brightness-110 shadow-[0_0_15px_rgba(99,102,241,0.3)]"
              )}
            >
              <Wrench className="w-4 h-4" />
              {isLoading ? 'Submitting...' : 'Repair code'}
            </button>
          </div>
        </section>

        {/* Centre Panel: READY STATE */}
        <section className="flex-1 flex flex-col border-r border-outline-variant bg-surface-container-lowest/30">
          <div className="h-10 px-4 flex items-center justify-between border-b border-outline-variant bg-surface-container-high/50">
            <h2 className="text-sm font-semibold text-on-surface-variant">Ready state</h2>
            <div className="flex gap-1">
              <div className="w-1 h-3 bg-secondary rounded-full"></div>
              <div className="w-1 h-3 bg-secondary rounded-full"></div>
              <div className="w-1 h-3 bg-outline-variant rounded-full"></div>
            </div>
          </div>
          <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
            <div className="relative mb-8">
              <div className="w-32 h-32 border border-primary/20 rounded-full animate-spin-slow absolute -inset-2"></div>
              <div className="w-32 h-32 border border-secondary/20 rounded-full animate-reverse-spin absolute -inset-4 opacity-50"></div>
              <div className="w-32 h-32 flex items-center justify-center border-2 border-outline-variant rounded-full relative bg-surface-container-low shadow-[0_0_30px_rgba(192,193,255,0.05)]">
                <RefreshCw className="w-14 h-14 text-primary animate-pulse" />
              </div>
            </div>
            <h3 className="text-base font-semibold text-on-surface mb-3">Awaiting submission</h3>
            <p className="max-w-[280px] text-sm text-on-surface-variant leading-relaxed font-mono opacity-75">
              The orchestrator is on standby. Paste the broken code to begin automatic repair synthesis.
            </p>
          </div>
        </section>

        {/* Right Panel: VAULT_PREVIEW */}
        <section className="w-1/3 flex flex-col bg-surface-container-low">
          <div className="h-10 px-4 flex items-center justify-between border-b border-outline-variant bg-surface-container-high/50">
            <h2 className="text-sm font-semibold text-on-surface-variant">Vault preview</h2>
            <div className="w-2 h-2 rounded-full bg-outline-variant animate-pulse"></div>
          </div>
          <div className="flex-1 flex flex-col items-center justify-center p-8 bg-gradient-to-b from-transparent to-surface-container-lowest/50">
            <div className="w-full aspect-square max-w-[280px] mb-8 relative group">
              <div className="absolute inset-0 border border-indigo-500/10 rotate-45 group-hover:rotate-90 transition-transform duration-1000"></div>
              <div className="absolute inset-4 border border-emerald-500/10 -rotate-12 group-hover:rotate-12 transition-transform duration-700"></div>
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-20 h-20 bg-gradient-to-br from-indigo-500/20 to-emerald-500/20 backdrop-blur-md border border-white/10 shadow-2xl flex items-center justify-center rounded-3xl">
                  <Box className="w-10 h-10 text-primary opacity-80" />
                </div>
              </div>
              {/* HUD Corner Accents */}
              <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-primary/40"></div>
              <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-secondary/40"></div>
            </div>
            <p className="text-sm font-medium text-on-surface-variant mb-6">
              Sourced patches will appear here once a repair run begins.
            </p>
            <div className="grid grid-cols-5 gap-2">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="w-6 h-1 bg-surface-container-highest rounded-full overflow-hidden">
                  <div className="h-full bg-primary/20 w-1/2"></div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
