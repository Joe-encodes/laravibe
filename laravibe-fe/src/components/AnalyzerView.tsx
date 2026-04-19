import React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Wrench, RefreshCw, Box } from 'lucide-react';
import { INITIAL_PHP_CODE, MASTER_REPAIR_TOKEN } from '../constants';

export const AnalyzerView: React.FC = () => {
  const navigate = useNavigate();
  const [code, setCode] = React.useState(INITIAL_PHP_CODE);
  const [prompt, setPrompt] = React.useState("");
  const [maxIterations, setMaxIterations] = React.useState(7);
  const [useBoost, setUseBoost] = React.useState(true);
  const [useMutationGate, setUseMutationGate] = React.useState(true);
  const [isLoading, setIsLoading] = React.useState(false);

  const handleRepair = async () => {
    setIsLoading(true);
    console.info('[LaraVibe] Initiating repair request...', { 
      max_iterations: maxIterations,
      use_boost: useBoost,
      use_mutation_gate: useMutationGate,
      has_prompt: !!prompt.trim()
    });
    try {
      const response = await fetch('/api/repair', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${MASTER_REPAIR_TOKEN}`
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
      if (!response.ok) throw new Error('API Request Failed');
      const data = await response.json();
      console.info('[LaraVibe] Submission ID:', data.submission_id);
      navigate(`/repair/${data.submission_id}`);
    } catch (e) {
      console.error(e);
      alert('Failed to submit repair request');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Left Panel: INPUT */}
      <section className="w-1/3 flex flex-col border-r border-outline-variant bg-surface-container-low">
        <div className="h-10 px-4 flex items-center justify-between border-b border-outline-variant bg-surface-container-high/50">
          <h2 className="mono text-xs font-bold tracking-widest text-on-surface-variant">INPUT</h2>
          <div className="flex gap-2">
            {/* Removed non-functional buttons */}
          </div>
        </div>
        <div className="flex-1 flex flex-col gap-3 overflow-auto bg-surface-container-lowest p-4 font-mono text-sm leading-relaxed text-primary/80">
          <div className="flex flex-col gap-1 shrink-0">
            <label className="mono text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">Dev Context / Instructions (Optional)</label>
            <textarea 
              className="w-full h-16 bg-surface-container-highest border border-outline-variant rounded p-2 text-xs text-primary/80 outline-none focus:border-primary transition-colors resize-none placeholder:text-outline-variant/50"
              placeholder="e.g. Please use the Repository pattern, or ignore the missing interface..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              spellCheck="false"
            />
          </div>
          <div className="flex-1 flex flex-col gap-1">
            <label className="mono text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">Broken Code</label>
            <textarea 
              className="w-full h-full bg-surface-container-highest border border-outline-variant rounded p-2 outline-none resize-none font-mono text-sm focus:border-primary transition-colors placeholder:text-outline-variant"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              spellCheck="false"
            />
          </div>
        </div>
        <div className="h-24 px-4 flex flex-col justify-center gap-3 border-t border-outline-variant bg-surface-container-low">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <label className="mono text-[10px] font-bold text-on-surface-variant">MAX ITERATIONS</label>
              <input 
                className="w-12 h-8 bg-surface-container-highest border-b-2 border-outline-variant text-center mono text-sm focus:border-primary outline-none transition-colors" 
                type="number" 
                value={maxIterations}
                onChange={(e) => setMaxIterations(Number(e.target.value))}
              />
            </div>
            
            <div className="flex gap-4">
              <label className="flex items-center gap-2 cursor-pointer group">
                <span className="mono text-[8px] font-bold text-on-surface-variant group-hover:text-primary transition-colors uppercase">Boost</span>
                <input type="checkbox" checked={useBoost} onChange={e => setUseBoost(e.target.checked)} className="accent-primary" />
              </label>
              <label className="flex items-center gap-2 cursor-pointer group">
                <span className="mono text-[8px] font-bold text-on-surface-variant group-hover:text-secondary transition-colors uppercase">Mutate</span>
                <input type="checkbox" checked={useMutationGate} onChange={e => setUseMutationGate(e.target.checked)} className="accent-secondary" />
              </label>
            </div>
          </div>
          
          <button 
            onClick={handleRepair}
            disabled={isLoading}
            className="w-full bg-[#6366F1] hover:bg-[#5254d8] disabled:opacity-50 text-white py-2 rounded-md mono text-xs font-bold tracking-tighter flex items-center justify-center gap-2 active:scale-95 transition-all shadow-lg shadow-indigo-500/20"
          >
            <Wrench className="w-4 h-4" />
            {isLoading ? 'SUBMITTING...' : 'REPAIR CODE'}
          </button>
        </div>
      </section>

      {/* Centre Panel: PROGRESS */}
      <section className="flex-1 flex flex-col border-r border-outline-variant bg-surface-container-lowest/30">
        <div className="h-10 px-4 flex items-center justify-between border-b border-outline-variant bg-surface-container-high/50">
          <h2 className="mono text-xs font-bold tracking-widest text-on-surface-variant">READY_STATE</h2>
          <div className="flex gap-1">
            <div className="w-1 h-3 bg-secondary"></div>
            <div className="w-1 h-3 bg-secondary"></div>
            <div className="w-1 h-3 bg-outline-variant"></div>
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
          <h3 className="font-mono text-xs font-bold text-on-surface uppercase tracking-[0.3em] mb-4">Awaiting Submission</h3>
          <p className="max-w-[240px] text-[10px] text-on-surface-variant leading-relaxed font-sans uppercase tracking-tight opacity-60">
            Orchestration engine is on standby. Inject broken logic into the kernel interface to begin automated synthesis.
          </p>
        </div>
      </section>

      {/* Right Panel: RESULT */}
      <section className="w-1/3 flex flex-col bg-surface-container-low">
        <div className="h-10 px-4 flex items-center justify-between border-b border-outline-variant bg-surface-container-high/50">
          <h2 className="mono text-xs font-bold tracking-widest text-on-surface-variant">VAULT_PREVIEW</h2>
          <div className="w-2 h-2 rounded-full bg-outline-variant animate-pulse"></div>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center p-8 bg-gradient-to-b from-transparent to-surface-container-lowest/50">
          <div className="w-full aspect-square max-w-[280px] mb-8 relative group">
            <div className="absolute inset-0 border border-indigo-500/10 rotate-45 group-hover:rotate-90 transition-transform duration-1000"></div>
            <div className="absolute inset-4 border border-emerald-500/10 -rotate-12 group-hover:rotate-12 transition-transform duration-700"></div>
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-20 h-20 bg-gradient-to-br from-indigo-500/20 to-emerald-500/20 backdrop-blur-md border border-white/10 shadow-2xl flex items-center justify-center">
                <Box className="w-10 h-10 text-primary opacity-80" />
              </div>
            </div>
            
            {/* HUD Accents */}
            <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-primary/40"></div>
            <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-secondary/40"></div>
          </div>
          <p className="text-[10px] mono font-bold text-outline uppercase tracking-[0.2em] mb-6">
            Sourced patches will materialize here
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
  );
};
