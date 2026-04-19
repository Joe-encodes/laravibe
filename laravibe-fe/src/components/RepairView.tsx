import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Cpu, RotateCw, AlertCircle, Brain } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { MASTER_REPAIR_TOKEN } from '../constants';

export const RepairView: React.FC = () => {
  const { submissionId } = useParams<{ submissionId: string }>();
  const navigate = useNavigate();
  const [logs, setLogs] = React.useState<any[]>([]);
  const [iteration, setIteration] = React.useState(0);
  const [maxIterations, setMaxIterations] = React.useState(7);
  const [ongoing, setOngoing] = React.useState(true);
  const [insight, setInsight] = React.useState<any>(null);
  const [stage, setStage] = React.useState<'IDLE' | 'SPINNING' | 'LINTING' | 'BOOSTING' | 'THINKING' | 'PATCHING' | 'TESTING' | 'MUTATING' | 'COMPLETE'>('SPINNING');
  const [stats, setStats] = React.useState({
    pestStatus: 'N/A',
    logicDepth: 0,
    boostContext: 'N/A',
    duration: 0
  });
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Auto-scroll logic
  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  React.useEffect(() => {
    if (!submissionId) return;
    
    setLogs([{ id: 'init', timestamp: new Date().toLocaleTimeString(), type: 'INFO', message: 'Connecting to repair stream...' }]);
    const eventSource = new EventSource(`/api/repair/${submissionId}/stream?token=${MASTER_REPAIR_TOKEN}`);

    eventSource.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data);
        console.info('[LaraVibe] SSE Event:', payload.event, payload.data);
        const { event, data } = payload;
        const ts = new Date().toLocaleTimeString();

        if (event === 'submission_start') {
          if (data.prompt) {
            setLogs(prev => [...prev, { 
              id: 'prompt', 
              timestamp: ts, 
              type: 'INFO', 
              message: `User Instructions: "${data.prompt}"` 
            }]);
          }
        } else if (event === 'log_line') {
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'INFO', message: data.msg }]);
          if (data.msg.includes('Spinning up')) setStage('SPINNING');
          if (data.msg.includes('Executing code')) setStage('LINTING');
          if (data.msg.includes('Injecting AI-generated Pest')) setStage('TESTING');
        } else if (event === 'iteration_start') {
          setIteration(data.iteration);
          setMaxIterations(data.max);
          setStage('SPINNING');
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'ITERATION', message: `Starting iteration ${data.iteration}/${data.max}` }]);
        } else if (event === 'boost_queried') {
          setStage('BOOSTING');
          setStats(prev => ({ ...prev, boostContext: data.component_type || 'Schema' }));
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'BOOST', message: `Refined context using ${data.component_type}...` }]);
        } else if (event === 'pest_result') {
          setStage('TESTING');
          setStats(prev => ({ 
            ...prev, 
            pestStatus: data.status.toUpperCase(),
            duration: prev.duration + (data.duration_ms || 0)
          }));
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'TEST', message: `Pest verification: ${data.status}` }]);
        } else if (event === 'mutation_result') {
          setStage('MUTATING');
          setStats(prev => ({ 
            ...prev, 
            mutationScore: data.score.toFixed(1),
            duration: prev.duration + (data.duration_ms || 0)
          }));
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'INFO', message: `Mutation score: ${data.score}% (${data.passed ? 'PASSED' : 'FAILED - TWEAKING'})` }]);
        } else if (event === 'ai_thinking') {
          setStage('THINKING');
          if (data.diagnosis) {
            setInsight({ title: data.diagnosis, description: data.fix_description });
          } else {
             setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'AI', message: `AI analyzing diagnostic signature...` }]);
          }
        } else if (event === 'patch_applied') {
          setStage('PATCHING');
          setStats(prev => ({ ...prev, logicDepth: prev.logicDepth + 1 }));
        } else if (event === 'complete') {
          setStage('COMPLETE');
          setOngoing(false);
          eventSource.close();
        } else if (event === 'error') {
          setLogs(prev => [...prev, { id: Math.random().toString(), timestamp: ts, type: 'INFO', message: `ERROR: ${data.msg}` }]);
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

    return () => {
      eventSource.close();
    };
  }, [submissionId]);
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Repair Header / Status */}
      <div className="p-6 border-b border-outline-variant bg-surface flex justify-between items-center">
      {/* Stage Stepper HUD */}
      <div className="bg-surface-container-low border-b border-outline-variant px-6 py-2 flex items-center justify-between">
        <div className="flex gap-4">
          {['SPINNING', 'BOOSTING', 'THINKING', 'PATCHING', 'TESTING', 'MUTATING'].map((item) => (
            <div key={item} className="flex items-center gap-2">
              <div className={cn(
                "w-1.5 h-1.5 rounded-full",
                stage === item ? "bg-primary animate-pulse shadow-[0_0_8px_#c0c1ff]" : (ongoing && logs.some(l => l.type === item) ? "bg-primary/40" : "bg-outline-variant")
              )}></div>
              <span className={cn(
                "mono text-[9px] font-bold tracking-tighter uppercase",
                stage === item ? "text-primary" : "text-outline"
              )}>{item}</span>
            </div>
          ))}
        </div>
        <div className="mono text-[10px] text-outline font-bold">STATE: <span className="text-on-surface">{stage}</span></div>
      </div>

      <div className="p-6 border-b border-outline-variant bg-surface flex justify-between items-center">
        <div className="flex items-center gap-4">
          <div className="p-2 bg-surface-container-high border border-outline-variant">
            <Cpu className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-mono font-extrabold tracking-tighter text-on-surface">REPAIR_SEQUENCE_{stage}</h1>
            <p className="font-sans text-xs text-outline tracking-widest uppercase">Target Hub: Sandbox_Core</p>
          </div>
        </div>
        <div className="flex items-center gap-6">
          <div className="text-right">
            <div className="font-mono text-3xl font-bold text-primary">{iteration} / {maxIterations}</div>
            <div className="font-sans text-[10px] text-outline uppercase tracking-tighter">ITERATION COUNTER</div>
          </div>
          <button 
            disabled={ongoing}
            onClick={() => navigate(`/iteration/${submissionId}`)}
            className={cn(
              "px-8 py-3 font-mono font-bold uppercase rounded-md flex items-center gap-3 transition-all",
              ongoing 
                ? "bg-surface-container-highest border-2 border-secondary text-secondary animate-pulse opacity-80 cursor-not-allowed" 
                : "bg-secondary text-on-primary border-2 border-secondary hover:brightness-110 shadow-lg shadow-secondary/20 active:scale-95 cursor-pointer"
            )}
          >
            {ongoing && <RotateCw className="w-5 h-5 animate-spin" />}
            {ongoing ? 'Repairing...' : 'Review Fixes'}
          </button>
        </div>
      </div>
      </div>

      {/* Streaming Logs Panel */}
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-6 font-mono text-sm space-y-2 bg-surface-container-lowest custom-scrollbar scroll-smooth"
      >
        <AnimatePresence initial={false}>
          {logs.map((log) => (
            <motion.div 
              key={log.id} 
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex gap-4 items-start py-1 border-l-2 border-outline-variant pl-4"
            >
              <span className="text-outline shrink-0 w-20">[{log.timestamp}]</span>
              <span className={cn(
                "px-1.5 py-0.5 text-[10px] font-bold border shrink-0",
                log.type === 'ITERATION' && "bg-primary/10 text-primary border-primary/30",
                log.type === 'INFO' && "bg-surface-container-high text-on-surface-variant border-outline-variant",
                log.type === 'BOOST' && "bg-secondary/10 text-secondary border-secondary/30",
                log.type === 'TEST' && "bg-tertiary/10 text-tertiary border-tertiary/30",
                log.type === 'AI' && "bg-indigo-500/20 text-indigo-400 border-indigo-500/40"
              )}>
                {log.type}
              </span>
              <span className="text-on-surface">{log.message}</span>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Expanded AI Diagnosis Block */}
        {insight && (
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="my-6 bg-surface-container-high border-2 border-primary/20 p-6 rounded-lg relative overflow-hidden shadow-2xl"
          >
            <div className="absolute top-0 right-0 p-2 opacity-10">
              <Brain className="w-32 h-32" />
            </div>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex items-center justify-center p-2 bg-primary/20 rounded-full">
                <Brain className="w-5 h-5 text-primary" />
              </div>
              <span className="font-bold text-primary uppercase text-sm tracking-widest">Diagnostic Insight Engine</span>
            </div>
            <div className="space-y-4 relative z-10">
              <div className="flex items-center gap-3 text-secondary">
                <AlertCircle className="w-5 h-5" />
                <span className="font-mono font-bold uppercase text-sm tracking-tight">{insight.title}</span>
              </div>
              <p className="text-on-surface-variant text-sm leading-relaxed max-w-2xl border-l-2 border-outline-variant/30 pl-4 py-1 italic">
                {insight.description}
              </p>
            </div>
            {/* Pulsing indicator */}
            <div className="absolute top-4 right-6 flex gap-1">
              <div className="w-1.5 h-1.5 bg-secondary rounded-full animate-pulse"></div>
              <div className="w-1.5 h-1.5 bg-secondary/40 rounded-full animate-pulse delay-75"></div>
            </div>
          </motion.div>
        )}

        {ongoing && logs.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-6 opacity-60">
            <div className="relative">
              <div className="w-16 h-16 border-2 border-primary/20 rounded-full animate-spin"></div>
              <div className="absolute inset-0 flex items-center justify-center">
                <Cpu className="w-6 h-6 text-primary animate-pulse" />
              </div>
            </div>
            <div className="space-y-2">
              <h3 className="mono text-xs font-bold tracking-[0.3em] uppercase">Booting_Sandbox_Vibe</h3>
              <p className="font-sans text-[10px] uppercase tracking-tighter">Establishing secure handshake with Laravel kernel...</p>
            </div>
          </div>
        )}

        {ongoing && logs.length > 0 && (
          <div className="flex gap-4 items-start py-1 border-l-2 border-outline-variant pl-4 animate-pulse">
            <span className="text-outline shrink-0 w-20">[{new Date().toLocaleTimeString()}]</span>
            <span className="text-secondary font-black animate-bounce">•</span>
            <span className="text-outline mono text-[10px] uppercase tracking-widest">Awaiting next sequence payload...</span>
          </div>
        )}
      </div>

      {/* Stats/Bento Bottom Grid */}
      <div className="grid grid-cols-4 gap-0 border-t border-outline-variant h-32 bg-surface-container-low">
        <div className="border-r border-outline-variant p-4 flex flex-col justify-between">
          <span className="font-sans text-[10px] text-outline uppercase tracking-widest">Logic Evolution</span>
          <div className="flex items-end gap-2">
            <span className="text-2xl font-mono font-bold">{stats.logicDepth}</span>
            <span className="text-[10px] text-secondary mb-1">PATCHES_APPLIED</span>
          </div>
        </div>
        <div className="border-r border-outline-variant p-4 flex flex-col justify-between">
          <span className="font-sans text-[10px] text-outline uppercase tracking-widest">Mutation Gate</span>
          <div className="w-full bg-surface-container-highest h-1.5 rounded-sm overflow-hidden">
            <div className="bg-primary h-full transition-all duration-1000" style={{ width: `${stats.mutationScore}%` }}></div>
          </div>
          <span className="text-xs font-mono font-bold">{stats.mutationScore}% <span className="text-outline">RECOIL_RESISTANCE</span></span>
        </div>
        <div className="border-r border-outline-variant p-4 flex flex-col justify-between">
          <span className="font-sans text-[10px] text-outline uppercase tracking-widest">Validation Status</span>
          <div className="flex gap-1">
            <div className={cn("h-4 w-1", stats.pestStatus === 'PASS' ? "bg-secondary" : "bg-surface-container-highest")}></div>
            <div className={cn("h-4 w-1", stats.pestStatus === 'PASS' ? "bg-secondary/60" : "bg-surface-container-highest")}></div>
            <div className={cn("h-4 w-1", stats.pestStatus === 'PASS' ? "bg-secondary/30" : "bg-surface-container-highest")}></div>
          </div>
          <span className={cn("text-xs font-mono font-bold uppercase", stats.pestStatus === 'PASS' ? "text-secondary" : "text-outline")}>{stats.pestStatus === 'PASS' ? 'PEST_VERIFIED' : 'AWAITING_PEST'}</span>
        </div>
        <div className="p-4 flex flex-col justify-between bg-primary/5">
          <span className="font-sans text-[10px] text-primary uppercase tracking-widest">Total Duration</span>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-mono font-bold text-primary">{(stats.duration / 1000).toFixed(1)}</span>
            <span className="text-[10px] text-primary/80 font-bold">SECONDS</span>
          </div>
          <span className="text-[10px] text-outline uppercase font-bold truncate">Context: {stats.boostContext}</span>
        </div>
      </div>
    </div>
  );
};
