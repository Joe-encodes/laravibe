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
  const [isHistory, setIsHistory] = React.useState(false);
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
    
    // Reset state on ID change
    setLogs([{ id: 'init', timestamp: new Date().toLocaleTimeString(), type: 'INFO', message: 'Establishing neural link to sandbox...' }]);
    setContexts([]);
    setPatches([]);
    setIteration(0);
    setInsight(null);
    setStage('SPINNING');
    setOngoing(true);
    setIsHistory(false);

    const sessionToken = localStorage.getItem('laravibe_session_token');
    const eventSource = new EventSource(`/api/repair/${submissionId}/stream?token=${sessionToken}`);

    eventSource.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data);
        const { event, data } = payload;
        const ts = new Date().toLocaleTimeString();

        if (event === 'submission_start') {
          setCurrentCode(data.original_code || "");
          if (data.history_replay) setIsHistory(true);
          if (data.prompt) {
            setLogs(prev => [...prev, { id: 'p', timestamp: ts, type: 'AI', message: `INIT_INSTRUCTION: "${data.prompt}"` }]);
          }
        } else if (event === 'log_line') {
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'INFO', message: data.msg || 'Unknown event' }]);
          if (data.msg && data.msg.includes('Spinning up')) setStage('SPINNING');
          if (data.msg && data.msg.includes('Executing code')) setStage('LINTING');
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
            pestStatus: data.status ? data.status.toUpperCase() : 'UNKNOWN',
            duration: prev.duration + (data.duration_ms || 0)
          }));
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'TEST', message: `PEST_GATE: ${data.status ? data.status.toUpperCase() : 'UNKNOWN'}` }]);
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
      <div className="h-16 border-b border-machined-border bg-surface-container-high/80 backdrop-blur-md flex items-center justify-between px-6 shrink-0 relative overflow-hidden z-20 shadow-md">
        
        <div className="flex items-center gap-4">
          <div className="p-2 bg-surface-container-high border border-outline-variant rounded relative">
            <Cpu className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-on-surface flex items-center gap-2">
              REPAIR_STREAM
              <button 
                onClick={() => navigator.clipboard.writeText(submissionId || '')}
                className="text-sm text-primary/70 font-semibold hover:text-primary transition-colors cursor-pointer"
                title="Copy ID"
              >
                [{submissionId?.substring(0, 8)}]
              </button>
              {isHistory && (
                <span className="ml-2 px-2 py-0.5 bg-amber-500/10 text-amber-500 border border-amber-500/30 text-[9px] font-black rounded uppercase">
                  History_Replay
                </span>
              )}
            </h1>
            <div className="flex items-center gap-4">
              <span className="text-hud text-outline/80">STATE: <span className="text-primary font-bold">{stage}</span></span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-10">
            <div className="flex flex-col items-center border-x border-machined-border px-6">
              <span className="text-[10px] font-bold text-outline/60 uppercase tracking-widest mb-1">MUTATION_GATE</span>
              <div className="flex items-center gap-2">
                <span className="mono text-lg font-black text-primary leading-none tracking-tighter">{stats.mutationScore}%</span>
                <div className="w-16 bg-surface-container-highest/50 h-1 rounded-full overflow-hidden">
                  <div className="bg-primary h-full" style={{ width: `${stats.mutationScore}%` }}></div>
                </div>
              </div>
            </div>

            <div className="flex flex-col items-center pr-6">
               <span className="text-[10px] font-bold text-outline/60 uppercase tracking-widest mb-1">VALIDATION</span>
                <div className={cn(
                  "px-2 py-0.5 mono text-[10px] font-black rounded-sm border flex items-center gap-2",
                  stats.pestStatus === 'PASS' 
                    ? "bg-secondary/10 text-secondary border-secondary/30" 
                    : stats.pestStatus === 'FAIL' 
                      ? "bg-error/10 text-error border-error/30 animate-pulse"
                      : "bg-outline-variant/10 text-outline border-outline-variant/20"
                )}>
                  {stats.pestStatus === 'PASS' ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                  {stats.pestStatus === 'PASS' ? 'LOGIC_VERIFIED' : stats.pestStatus === 'FAIL' ? 'LOGIC_CRASHED' : 'GATE_PENDING'}
                </div>
            </div>

            <div className="flex flex-col items-end border-l border-machined-border pl-6">
              <span className="mono text-lg font-black text-primary leading-none tracking-tighter">{iteration} / {maxIterations}</span>
              <span className="text-[10px] font-bold text-outline/60 uppercase tracking-widest mt-1">CYCLE_COUNT</span>
            </div>
            
            <div className="flex gap-2">
              <button 
                disabled={ongoing}
                onClick={() => navigate(`/iteration/${submissionId}`)}
                className={cn(
                  "px-5 py-1.5 font-mono text-[10px] font-black uppercase rounded border transition-all flex items-center gap-2",
                  ongoing 
                    ? "border-outline-variant/30 text-outline/50 cursor-wait bg-surface-container-highest/20" 
                    : "bg-secondary/10 text-secondary border-secondary/50 hover:bg-secondary/20 hover:border-secondary active:scale-95"
                )}
              >
                {ongoing ? <RotateCw className="w-3 h-3 animate-spin" /> : <TerminalIcon className="w-3 h-3" />}
                {ongoing ? 'SYNCHRONISING...' : 'VIEW_DIFF'}
              </button>
            </div>
          </div>
        </div>

      {/* Main 3-Panel HUD */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* Panel 1: Discovery (Left) */}
        <ContextDiscoveryPanel contexts={contexts} />

        {/* Panel 2: Terminal (Center) */}
        <section className="flex-1 flex flex-col min-w-0 bg-surface-container-lowest relative">
          <div className="h-12 px-6 flex items-center justify-between border-b border-machined-border bg-surface-container-high/30 backdrop-blur-md shrink-0 relative z-10">
            <div className="flex items-center gap-2">
              <TerminalIcon className="w-4 h-4 text-primary" />
              <h2 className="text-hud text-on-surface-variant">COMMAND_LOG</h2>
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

            {ongoing && !isHistory && (
              <div className="flex gap-3 items-center opacity-40 py-2">
                <div className="w-1 h-1 bg-primary rounded-full animate-pulse"></div>
                <span className="text-xs text-on-surface-variant">Waiting for sandbox payload...</span>
              </div>
            )}
            {/* AI Diagnosis Toast in Terminal */}
            {insight && ongoing && (
              <motion.div 
                initial={{ opacity: 0, y: 10, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                className="my-6 bg-surface-container-high border-2 border-primary/40 p-6 rounded-xl relative overflow-hidden shadow-2xl ring-1 ring-primary/20"
              >
                <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent pointer-events-none"></div>
                <div className="flex items-center gap-3 mb-4 relative z-10">
                  <div className="p-1.5 bg-primary/20 rounded-lg">
                    <Brain className="w-5 h-5 text-primary" />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-hud text-primary leading-none">AI_STRATEGY_DECODED</span>
                    <span className="text-[8px] text-outline font-black uppercase tracking-widest mt-1">Real-time Diagnostic Insight</span>
                  </div>
                </div>
                <div className="relative z-10 pl-2 border-l-2 border-primary/30">
                  <h4 className="mono text-sm font-black text-on-surface mb-2 leading-tight uppercase tracking-tight">{insight.title}</h4>
                  <p className="text-log text-on-surface-variant italic leading-relaxed">{insight.description}</p>
                </div>
                {/* Decorative background brain */}
                <div className="absolute -bottom-4 -right-4 p-2 opacity-[0.05] pointer-events-none scale-150 rotate-12">
                  <Brain className="w-24 h-24 text-primary" />
                </div>
              </motion.div>
            )}
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
