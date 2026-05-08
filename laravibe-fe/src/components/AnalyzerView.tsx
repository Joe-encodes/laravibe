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
        <section className="w-1/3 min-w-[300px] max-w-[50vw] resize-x overflow-auto flex flex-col border-r border-machined-border machined-panel z-10 shadow-2xl">
          <div className="h-12 px-4 flex items-center justify-between border-b border-machined-border bg-surface-container-high/80 backdrop-blur-sm">
            <h2 className="text-hud text-on-surface-variant flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse" />
              INPUT_STREAM
            </h2>
          </div>
          <div className="flex-1 flex flex-col gap-4 overflow-auto bg-surface-container-lowest/50 p-5 text-sm leading-relaxed text-primary/80">
            <div className="flex flex-col gap-1.5 shrink-0 relative group">
              <label className="text-hud text-primary opacity-80 group-focus-within:opacity-100 transition-opacity flex justify-between">
                <span>CONTEXT_NOTES</span>
                <span className="text-[8px] opacity-50">OPTIONAL</span>
              </label>
              <div className="relative">
                <div className="absolute -inset-0.5 bg-primary/20 rounded-lg blur opacity-0 group-focus-within:opacity-100 transition duration-500"></div>
                <textarea 
                  className="relative w-full h-20 bg-surface-container/50 border border-primary/20 rounded-lg p-3 text-sm text-on-surface outline-none focus:border-primary focus:bg-surface-container/80 transition-all resize-y placeholder:text-on-surface-variant/30 custom-scrollbar shadow-inner"
                  placeholder="Describe the problem or paste relevant context."
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  spellCheck="false"
                />
              </div>
            </div>
            <div className="flex-1 flex flex-col gap-1.5 relative group">
              <label className="text-hud text-sky-400 opacity-80 group-focus-within:opacity-100 transition-opacity">SOURCE_CODE</label>
              <div className="relative flex-1 flex flex-col">
                <div className="absolute -inset-0.5 bg-sky-500/20 rounded-lg blur opacity-0 group-focus-within:opacity-100 transition duration-500"></div>
                <textarea 
                  className="relative flex-1 w-full bg-surface-container/50 border border-sky-500/20 rounded-lg p-4 outline-none resize-y font-mono text-sm text-on-surface focus:border-sky-500 focus:bg-surface-container/80 transition-all placeholder:text-on-surface-variant/20 leading-relaxed custom-scrollbar shadow-inner"
                  placeholder={'<?php\n\n// Paste your broken Laravel code here...\n// The system will analyze errors and generate a patch.'}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  spellCheck="false"
                />
              </div>
            </div>
          </div>
          <div className="p-5 flex flex-col justify-center gap-4 border-t border-machined-border bg-surface-container-high/30 backdrop-blur-md">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 bg-surface-container/50 px-3 py-1.5 rounded-md border border-outline-variant/30">
                <label className="text-hud text-secondary">ITERATIONS</label>
                <input 
                  className="w-12 bg-transparent text-center text-sm font-mono text-secondary font-bold focus:outline-none" 
                  type="number" 
                  min={1}
                  max={15}
                  value={maxIterations}
                  onChange={(e) => setMaxIterations(Number(e.target.value))}
                />
              </div>
              
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer group">
                  <span className="text-hud text-on-surface-variant group-hover:text-primary transition-colors">BOOST</span>
                  <div className="relative flex items-center justify-center">
                    <input type="checkbox" checked={useBoost} onChange={e => setUseBoost(e.target.checked)} className="peer sr-only" />
                    <div className="w-8 h-4 bg-surface-container-highest rounded-full peer-checked:bg-primary/30 transition-colors border border-outline-variant peer-checked:border-primary/50"></div>
                    <div className="absolute left-0 w-4 h-4 bg-outline-variant rounded-full peer-checked:bg-primary peer-checked:translate-x-full transition-transform shadow-sm"></div>
                  </div>
                </label>
                <label className="flex items-center gap-2 cursor-pointer group">
                  <span className="text-hud text-on-surface-variant group-hover:text-secondary transition-colors">MUTATE</span>
                  <div className="relative flex items-center justify-center">
                    <input type="checkbox" checked={useMutationGate} onChange={e => setUseMutationGate(e.target.checked)} className="peer sr-only" />
                    <div className="w-8 h-4 bg-surface-container-highest rounded-full peer-checked:bg-secondary/30 transition-colors border border-outline-variant peer-checked:border-secondary/50"></div>
                    <div className="absolute left-0 w-4 h-4 bg-outline-variant rounded-full peer-checked:bg-secondary peer-checked:translate-x-full transition-transform shadow-sm"></div>
                  </div>
                </label>
              </div>
            </div>
            
            <button 
              onClick={handleRepair}
              disabled={isLoading || !code.trim()}
              className={cn(
                "w-full py-3.5 rounded-lg text-hud flex items-center justify-center gap-2 active:scale-[0.98] transition-all relative overflow-hidden group",
                isLoading || !code.trim()
                  ? "bg-surface-container-highest/50 text-outline cursor-not-allowed border border-outline-variant/30"
                  : "bg-primary text-on-primary border border-primary/50 primary-glow hover:bg-primary-fixed"
              )}
            >
              {(!isLoading && code.trim()) && (
                <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000"></div>
              )}
              <Wrench className="w-4 h-4 relative z-10" />
              <span className="relative z-10">{isLoading ? 'INITIALIZING_SEQUENCE...' : 'ENGAGE_REPAIR_PROTOCOL'}</span>
            </button>
          </div>
        </section>

        {/* Centre Panel: READY STATE */}
        <section className="flex-1 flex flex-col bg-surface-container-lowest relative overflow-hidden">
          {/* Subtle grid background */}
          <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:40px_40px] pointer-events-none"></div>
          
          <div className="h-12 px-6 flex items-center justify-between border-b border-machined-border bg-surface-container-high/30 backdrop-blur-md relative z-10">
            <h2 className="text-hud text-on-surface-variant tracking-[0.2em]">ORCHESTRATOR_STATUS</h2>
            <div className="flex gap-1.5">
              <div className="w-1.5 h-4 bg-secondary/80 rounded-sm shadow-[0_0_8px_rgba(78,222,163,0.5)]"></div>
              <div className="w-1.5 h-4 bg-secondary/50 rounded-sm"></div>
              <div className="w-1.5 h-4 bg-outline-variant/30 rounded-sm"></div>
            </div>
          </div>
          <div className="flex-1 flex flex-col items-center justify-center text-center p-8 relative z-10">
            <div className="relative mb-12">
              <div className="w-40 h-40 border-2 border-primary/10 rounded-full animate-spin-slow absolute -inset-4"></div>
              <div className="w-40 h-40 border border-secondary/20 rounded-full animate-reverse-spin absolute -inset-8 opacity-40"></div>
              {/* Added a third ring for depth */}
              <div className="w-40 h-40 border border-indigo-500/10 rounded-full animate-spin-slow absolute -inset-12 [animation-duration:15s]"></div>
              
              <div className="w-32 h-32 flex items-center justify-center border border-outline-variant/50 rounded-full relative bg-surface-container-low/80 backdrop-blur-sm shadow-[0_0_40px_rgba(192,193,255,0.1)] before:absolute before:inset-2 before:border before:border-primary/20 before:rounded-full">
                <RefreshCw className="w-12 h-12 text-primary opacity-80" />
              </div>
            </div>
            <h3 className="text-hud text-on-surface mb-4 text-lg">SYSTEM_STANDBY</h3>
            <p className="max-w-[320px] text-log text-on-surface-variant/80">
              Neural orchestrator initialized. Awaiting syntax injection to commence repair protocol.
            </p>
          </div>
        </section>

        {/* Right Panel: VAULT_PREVIEW */}
        <section className="w-1/4 flex flex-col border-l border-machined-border machined-panel z-10 shadow-[-10px_0_20px_rgba(0,0,0,0.2)]">
          <div className="h-12 px-4 flex items-center justify-between border-b border-machined-border bg-surface-container-high/80 backdrop-blur-sm">
            <h2 className="text-hud text-on-surface-variant tracking-[0.2em]">VAULT_PREVIEW</h2>
            <div className="w-2 h-2 rounded-sm bg-outline-variant/50"></div>
          </div>
          <div className="flex-1 flex flex-col items-center justify-center p-8 bg-gradient-to-b from-transparent to-surface-container-highest/10 relative">
            
            <div className="w-full aspect-square max-w-[220px] mb-8 relative group">
              {/* Elaborate wireframe box */}
              <div className="absolute inset-0 border border-indigo-500/20 rotate-45 group-hover:rotate-90 group-hover:border-indigo-500/40 transition-all duration-1000 ease-in-out"></div>
              <div className="absolute inset-4 border border-emerald-500/20 -rotate-12 group-hover:rotate-12 group-hover:border-emerald-500/40 transition-all duration-700 ease-in-out"></div>
              <div className="absolute inset-8 border border-primary/10 rotate-180 group-hover:-rotate-45 transition-all duration-[1200ms] ease-in-out"></div>
              
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-16 h-16 bg-surface-container-low/80 backdrop-blur-md border border-white/10 flex items-center justify-center rounded-xl shadow-[0_0_30px_rgba(99,102,241,0.15)] group-hover:shadow-[0_0_40px_rgba(99,102,241,0.3)] transition-shadow duration-500">
                  <Box className="w-8 h-8 text-primary opacity-60 group-hover:opacity-100 transition-opacity" />
                </div>
              </div>
              {/* HUD Corner Accents */}
              <div className="absolute top-0 left-0 w-3 h-3 border-t border-l border-primary/40"></div>
              <div className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-secondary/40"></div>
              <div className="absolute top-0 right-0 w-3 h-3 border-t border-r border-outline-variant/40"></div>
              <div className="absolute bottom-0 left-0 w-3 h-3 border-b border-l border-outline-variant/40"></div>
            </div>
            
            <div className="w-full max-w-[200px] flex flex-col gap-3">
              <div className="flex justify-between items-end mb-2 border-b border-outline-variant/30 pb-2">
                <span className="text-hud text-outline">MEMORY_BANKS</span>
                <span className="text-hud text-primary">OFFLINE</span>
              </div>
              {[...Array(4)].map((_, i) => (
                <div key={i} className="w-full h-1 bg-surface-container-highest rounded-full overflow-hidden relative">
                  <div className="absolute inset-y-0 left-0 bg-primary/10 w-1/3"></div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
