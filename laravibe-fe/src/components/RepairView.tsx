import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Cpu, RotateCw, AlertCircle, Brain, Terminal as TerminalIcon } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { MASTER_REPAIR_TOKEN } from '../constants';
import { ContextDiscoveryPanel } from './ContextDiscoveryPanel';
import { CodeSynthesisPanel } from './CodeSynthesisPanel';
import { BoostContext, Patch } from '../types';

export const RepairView: React.FC = () => {
  const { submissionId } = useParams<{ submissionId: string }>();
  const navigate = useNavigate();
  
  // State
  const [logs, setLogs] = React.useState<any[]>([]);
  const [contexts, setContexts] = React.useState<BoostContext[]>([]);
  const [currentCode, setCurrentCode] = React.useState<string>("");
  const [patches, setPatches] = React.useState<Patch[]>([]);
  const [iteration, setIteration] = React.useState(0);
  const [maxIterations, setMaxIterations] = React.useState(7);
  const [ongoing, setOngoing] = React.useState(true);
  const [insight, setInsight] = React.useState<any>(null);
  const [stage, setStage] = React.useState<'IDLE' | 'SPINNING' | 'LINTING' | 'BOOSTING' | 'THINKING' | 'PATCHING' | 'TESTING' | 'MUTATING' | 'COMPLETE'>('SPINNING');
  const [stats, setStats] = React.useState({
    pestStatus: 'N/A',
    logicDepth: 0,
    mutationScore: 0 as number,
    duration: 0
  });
  
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Auto-scroll logic for terminal
  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  // SSE Stream Logic
  React.useEffect(() => {
    if (!submissionId) return;
    
    setLogs([{ id: 'init', timestamp: new Date().toLocaleTimeString(), type: 'INFO', message: 'Establishing neural link to sandbox...' }]);
    const sessionToken = localStorage.getItem('laravibe_session_token');
    const eventSource = new EventSource(`/api/repair/${submissionId}/stream?token=${sessionToken}`);

    eventSource.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data);
        const { event, data } = payload;
        const ts = new Date().toLocaleTimeString();

        if (event === 'submission_start') {
          setCurrentCode(data.original_code || "");
          if (data.prompt) {
            setLogs(prev => [...prev, { id: 'p', timestamp: ts, type: 'AI', message: `INIT_INSTRUCTION: "${data.prompt}"` }]);
          }
        } else if (event === 'log_line') {
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'INFO', message: data.msg }]);
          if (data.msg.includes('Spinning up')) setStage('SPINNING');
          if (data.msg.includes('Executing code')) setStage('LINTING');
        } else if (event === 'iteration_start') {
          setIteration(data.iteration);
          setMaxIterations(data.max);
          setStage('SPINNING');
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'ITERATION', message: `SYNTHESIS_CYCLE_${data.iteration}/${data.max}_START` }]);
        } else if (event === 'boost_queried') {
          setStage('BOOSTING');
          const newCtx: BoostContext = {
            component_type: data.component_type || 'Unknown',
            context_text: data.context_text || 'Injected schema/docs context.',
            schema: data.schema
          };
          setContexts(prev => [...prev, newCtx]);
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'BOOST', message: `BOOST: Contextualized ${data.component_type} architecture` }]);
        } else if (event === 'pest_result') {
          setStage('TESTING');
          setStats(prev => ({ 
            ...prev, 
            pestStatus: data.status.toUpperCase(),
            duration: prev.duration + (data.duration_ms || 0)
          }));
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'TEST', message: `PEST_GATE: ${data.status.toUpperCase()}` }]);
        } else if (event === 'mutation_result') {
          setStage('MUTATING');
          setStats(prev => ({ 
            ...prev, 
            mutationScore: typeof data.score === 'number' ? data.score : parseFloat(data.score ?? '0'),
            duration: prev.duration + (data.duration_ms || 0)
          }));
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'INFO', message: `MUTATION_SCORE: ${data.score}%` }]);
        } else if (event === 'ai_thinking') {
          setStage('THINKING');
          if (data.diagnosis) {
            setInsight({ title: data.diagnosis, description: data.fix_description });
          }
        } else if (event === 'patch_applied') {
          setStage('PATCHING');
          const newPatch: Patch = {
            path: data.target || data.path || 'unknown.php',
            action: data.action || 'full_replace',
            content: data.replacement || ""
          };
          setPatches(prev => [...prev, newPatch]);
          if (data.updated_code) setCurrentCode(data.updated_code);
          setStats(prev => ({ ...prev, logicDepth: prev.logicDepth + 1 }));
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'AI', message: `PATCH_APPLIED: ${newPatch.path}` }]);
        } else if (event === 'complete') {
          setStage('COMPLETE');
          setOngoing(false);
          if (data.final_code) setCurrentCode(data.final_code);
          eventSource.close();
        } else if (event === 'error') {
          const errMsg = data.message || data.msg || 'Unknown error';
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'ERROR', message: `SYS_ERROR: ${errMsg}` }]);
          setStage('COMPLETE');
          setOngoing(false);
          eventSource.close();
        }
      } catch (err) {
        console.error('SSE parse error:', err);
      }
    };

    eventSource.onerror = (err) => {
      console.error('SSE connection error:', err);
      eventSource.close();
      setOngoing(false);
    };

    return () => eventSource.close();
  }, [submissionId]);

  const handleDownload = () => {
    const blob = new Blob([currentCode], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `repaired_${submissionId?.substring(0, 8)}.php`;
    a.click();
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-surface-container-lowest">
      {/* Header HUD */}
      <div className="h-16 border-b border-outline-variant bg-surface-container-low flex items-center justify-between px-6 shrink-0 relative overflow-hidden">
        {/* Glass Glow Accent */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-1 bg-primary/20 blur-md"></div>
        
        <div className="flex items-center gap-4">
          <div className="p-2 bg-surface-container-high border border-outline-variant rounded relative group">
            <Cpu className="w-5 h-5 text-primary group-hover:animate-pulse" />
            <div className="absolute inset-0 bg-primary/10 blur-sm rounded animate-pulse opacity-0 group-hover:opacity-100"></div>
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-on-surface flex items-center gap-2">
              Repair stream
              <button 
                onClick={() => navigator.clipboard.writeText(submissionId || '')}
                className="text-sm text-primary/70 font-semibold hover:text-primary transition-colors cursor-pointer"
                title="Copy ID"
              >
                [{submissionId?.substring(0, 8)}]
              </button>
            </h1>
            <div className="flex items-center gap-4">
              <div className="flex gap-1.5">
                {['SPINNING', 'BOOSTING', 'THINKING', 'PATCHING', 'TESTING', 'MUTATING'].map((s) => (
                  <div 
                    key={s} 
                    className={cn(
                      "w-1 h-1 rounded-full transition-all duration-500",
                      stage === s ? "bg-primary scale-150 shadow-[0_0_8px_rgba(192,193,255,1)]" : "bg-outline-variant"
                    )} 
                  />
                ))}
              </div>
              <span className="text-xs text-outline">Current state: <span className="text-primary">{stage.toLowerCase()}</span></span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-8">
          <div className="flex flex-col items-end">
            <span className="mono text-[10px] font-black text-primary leading-none tracking-tighter">{iteration} / {maxIterations}</span>
            <span className="mono text-[8px] text-outline uppercase font-bold tracking-widest mt-1">Cycle_Count</span>
          </div>
          <button 
            disabled={ongoing}
            onClick={() => navigate(`/iteration/${submissionId}`)}
            className={cn(
              "px-6 py-2 font-mono text-[10px] font-black uppercase rounded border transition-all flex items-center gap-2",
              ongoing 
                ? "border-outline-variant text-outline opacity-50 cursor-wait" 
                : "bg-secondary text-on-secondary border-secondary hover:brightness-110 active:scale-95 shadow-lg shadow-secondary/10"
            )}
          >
            {ongoing ? <RotateCw className="w-3 h-3 animate-spin" /> : <TerminalIcon className="w-3 h-3" />}
            {ongoing ? 'Synchronising...' : 'View_Detailed_Diff'}
          </button>
        </div>
      </div>

      {/* Main 3-Panel HUD */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* Panel 1: Discovery (Left) */}
        <ContextDiscoveryPanel contexts={contexts} />

        {/* Panel 2: Terminal (Center) */}
        <section className="flex-1 flex flex-col min-w-0 bg-surface-container-lowest relative">
          <div className="h-10 px-4 flex items-center justify-between border-b border-outline-variant bg-surface-container-high/30 shrink-0">
            <div className="flex items-center gap-2">
              <TerminalIcon className="w-3 h-3 text-outline" />
              <h2 className="text-sm font-semibold text-on-surface-variant">Command log</h2>
            </div>
          </div>
          
          <div 
            ref={scrollRef}
            className="flex-1 overflow-y-auto p-4 font-mono text-[11px] space-y-2 custom-scrollbar scroll-smooth"
          >
            <AnimatePresence initial={false}>
              {logs.map((log) => (
                <motion.div 
                  key={log.id} 
                  initial={{ opacity: 0, x: -5 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex gap-3 items-start group"
                >
                  <span className="text-outline/40 shrink-0 select-none">[{log.timestamp}]</span>
                  <span className={cn(
                    "px-1.5 py-0.5 font-black text-[9px] shrink-0 border rounded-sm",
                    log.type === 'ITERATION' && "text-primary border-primary/30 bg-primary/10",
                    log.type === 'BOOST'     && "text-secondary border-secondary/30 bg-secondary/10",
                    log.type === 'AI'        && "text-violet-400 border-violet-400/30 bg-violet-400/10",
                    log.type === 'TEST'      && "text-emerald-400 border-emerald-400/30 bg-emerald-400/10",
                    log.type === 'ERROR'     && "text-red-400 border-red-400/30 bg-red-400/10",
                    log.type === 'INFO'      && "text-sky-400/70 border-sky-400/20 bg-transparent"
                  )}>
                    {log.type}
                  </span>
                  <span className="text-on-surface/90 break-words">{log.message}</span>
                </motion.div>
              ))}
            </AnimatePresence>

            {ongoing && (
              <div className="flex gap-3 items-center opacity-40 py-2 animate-pulse">
                <div className="w-1 h-1 bg-primary rounded-full animate-bounce"></div>
                <span className="text-sm text-on-surface-variant">Waiting for sandbox payload...</span>
              </div>
            )}
            {/* AI Diagnosis Toast in Terminal */}
            {insight && ongoing && (
              <motion.div 
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="my-4 bg-indigo-500/10 border border-indigo-500/30 p-4 rounded-md relative overflow-hidden"
              >
                <div className="flex items-center gap-2 mb-2">
                  <Brain className="w-3 h-3 text-indigo-400" />
                  <span className="text-sm font-semibold text-indigo-400">AI diagnosis</span>
                </div>
                <h4 className="mono text-[11px] font-bold text-indigo-300 mb-1">{insight.title}</h4>
                <p className="text-[10px] text-on-surface-variant italic leading-relaxed">{insight.description}</p>
                <div className="absolute top-0 right-0 p-2 opacity-5">
                  <Brain className="w-12 h-12" />
                </div>
              </motion.div>
            )}
          </div>

          {/* Bento Stats Footer */}
          <div className="h-20 grid grid-cols-3 border-t border-outline-variant bg-surface-container-low shrink-0">
            <div className="border-r border-outline-variant p-3 flex flex-col justify-between">
              <span className="mono text-[8px] text-outline font-black uppercase tracking-widest">Mutation_Gate</span>
              <div className="flex items-center justify-between">
                <span className="mono text-lg font-black text-primary">{stats.mutationScore}%</span>
                <div className="w-20 bg-surface-container-highest h-1 rounded-full overflow-hidden">
                  <div className="bg-primary h-full transition-all duration-1000" style={{ width: `${stats.mutationScore}%` }}></div>
                </div>
              </div>
            </div>
            <div className="border-r border-outline-variant p-3 flex flex-col justify-between">
              <span className="mono text-[8px] text-outline font-black uppercase tracking-widest">Validation_Gate</span>
              <div className="flex items-center gap-2">
                <div className={cn(
                  "px-2 py-0.5 mono text-[10px] font-black rounded",
                  stats.pestStatus === 'PASS' ? "bg-secondary/20 text-secondary border border-secondary/30" : "bg-outline-variant/20 text-outline"
                )}>
                  {stats.pestStatus}
                </div>
                <span className="mono text-[8px] text-outline font-bold uppercase truncate">{stats.pestStatus === 'PASS' ? 'Logic_Verified' : 'Awaiting_Gate'}</span>
              </div>
            </div>
            <div className="p-3 flex flex-col justify-between bg-primary/5">
              <span className="mono text-[8px] text-primary font-black uppercase tracking-widest">Latency_Metrics</span>
              <div className="flex items-baseline gap-1">
                <span className="mono text-lg font-black text-primary">{(stats.duration / 1000).toFixed(1)}</span>
                <span className="mono text-[9px] text-primary/60 font-black">SEC</span>
              </div>
            </div>
          </div>
        </section>

        {/* Panel 3: Synthesis (Right) */}
        <CodeSynthesisPanel 
          code={currentCode} 
          patches={patches} 
          isComplete={stage === 'COMPLETE'}
          onDownload={handleDownload}
        />

      </div>
    </div>
  );
};
