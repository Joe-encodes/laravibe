import React from 'react';
import { useParams } from 'react-router-dom';
import { Download, ChevronLeft, CheckCircle2, FileCode, History, Layers, Terminal, AlertCircle, Brain } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { MASTER_REPAIR_TOKEN } from '../constants';

export const IterationView: React.FC = () => {
  const { submissionId } = useParams<{ submissionId: string }>();
  const [submission, setSubmission] = React.useState<any>(null);
  const [tab, setTab] = React.useState<'original' | 'repaired' | 'audit'>('repaired');
  const [selectedIteration, setSelectedIteration] = React.useState<number>(0);

  React.useEffect(() => {
    if (!submissionId) return;
    const load = async () => {
      console.info('[LaraVibe] Loading iteration details...', { submissionId });
      try {
        const sessionToken = localStorage.getItem('laravibe_session_token');
        const res = await fetch(`/api/repair/${submissionId}`, {
          headers: {
            'Authorization': `Bearer ${sessionToken}`
          }
        });
        console.info('[LaraVibe] Repair API Response:', { status: res.status });
        const data = await res.json();
        console.info('[LaraVibe] Data retrieved:', { status: data.status, iters: data.iterations?.length });
        setSubmission(data);
      } catch (err) {
        console.error(err);
      }
    };
    load();
  }, [submissionId]);

  if (!submission) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface-container-lowest">
        <div className="flex flex-col items-center gap-4 animate-pulse">
          <Terminal className="w-12 h-12 text-outline" />
          <span className="mono text-xs font-bold text-outline uppercase tracking-widest">Initialising_Data_Link...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-surface-container-lowest overflow-hidden">
      {/* Header Section */}
      <div className="p-8 border-b border-outline-variant bg-surface-container-low relative overflow-hidden">
        <div className="absolute top-0 right-0 p-8 opacity-5">
          <Layers className="w-48 h-48 rotate-12" />
        </div>
        
        <div className="relative z-10 flex justify-between items-start">
          <div>
            <div className="flex items-center gap-3 mb-4">
              <span className={cn(
                "text-[10px] px-2 py-0.5 rounded font-black uppercase font-mono tracking-widest bg-opacity-20",
                submission.status === 'success' ? "bg-secondary text-secondary" : "bg-error text-error"
              )}>
                STATUS: {submission.status}
              </span>
              <div className="h-4 w-px bg-outline-variant"></div>
              <span className="text-outline text-[10px] font-mono font-bold">NODE_ID: {submission.id?.substring(0,8)}</span>
            </div>
            <h1 className="text-4xl font-mono font-black text-on-surface tracking-tighter leading-none mb-3 uppercase italic">
              REPAIR_CYCLE_SUMMARY
            </h1>
            <div className="flex items-center gap-2 text-on-surface-variant max-w-2xl font-mono text-sm">
              <Terminal className="w-4 h-4 shrink-0 text-primary" />
              <span>Target analysis completed with <span className="text-primary font-bold">{submission.iterations?.length || 0} iterations</span>. Logic verified against Pest test suite.</span>
            </div>
            {submission.user_prompt && (
              <div className="mt-4 p-3 bg-primary/5 border border-primary/20 rounded-md">
                <div className="flex items-center gap-2 mb-1">
                  <Brain className="w-3 h-3 text-primary" />
                  <span className="mono text-[8px] font-black uppercase text-primary tracking-widest">Developer Context</span>
                </div>
                <p className="text-on-surface-variant text-xs font-mono leading-tight pl-5 border-l border-primary/20">
                  {submission.user_prompt}
                </p>
              </div>
            )}
          </div>
          <div className="flex gap-4">
            <button 
              onClick={() => {
                const blob = new Blob([submission.final_code], { type: 'text/plain' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `repaired_${submissionId}.php`;
                a.click();
              }}
              className="flex items-center gap-2 bg-primary text-on-primary px-6 py-3 text-xs font-mono font-black uppercase tracking-widest hover:brightness-110 active:scale-95 transition-all shadow-lg shadow-primary/20 rounded-md"
            >
              <Download className="w-4 h-4" />
              Direct_Export
            </button>
          </div>
        </div>
      </div>

      {/* Dashboard Grid */}
      <div className="flex-1 grid grid-cols-12 overflow-hidden">
        {/* Left Panel: Logs */}
        <div className="col-span-4 border-r border-outline-variant p-0 flex flex-col bg-surface-container-lowest overflow-hidden">
          <div className="px-6 py-4 border-b border-outline-variant flex justify-between items-center bg-surface-container-low">
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-outline" />
              <span className="font-mono text-[10px] uppercase font-bold text-on-surface">Execution_Timeline</span>
            </div>
            <div className="flex gap-1">
              <div className="w-1 h-3 bg-secondary"></div>
              <div className="w-1 h-3 bg-secondary/40"></div>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4 font-mono text-[11px] space-y-4 bg-surface-container-lowest custom-scrollbar pb-12">
            {submission.iterations?.map((iter: any, idx: number) => (
              <div 
                key={iter.id} 
                onClick={() => setSelectedIteration(idx)}
                className={cn(
                  "group transition-all p-3 cursor-pointer rounded border border-transparent",
                  selectedIteration === idx ? "bg-primary/5 border-primary/20" : "hover:bg-surface-container-high"
                )}
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className={cn(
                    "w-2 h-2 rounded-full transition-colors",
                    selectedIteration === idx ? "bg-primary shadow-[0_0_8px_rgba(192,193,255,0.5)]" : "bg-primary/40 group-hover:bg-primary"
                  )}></div>
                  <span className="text-primary font-black uppercase tracking-tighter">Iteration_{iter.iteration_num}</span>
                  <span className="text-outline text-[9px] ml-auto">{iter.duration_ms}ms</span>
                </div>
                <div className="pl-4 border-l border-outline-variant/30 ml-1 space-y-2 py-1">
                   {iter.error_logs && (
                     <div className="flex gap-2">
                       <AlertCircle className="w-3 h-3 text-error shrink-0 mt-0.5" />
                       <div className="text-error/80 leading-relaxed font-mono text-[10px]">
                         {iter.error_logs.substring(0, 150)}...
                       </div>
                     </div>
                   )}
                   {iter.patch_applied && (
                     <div className="flex gap-2">
                       <CheckCircle2 className="w-3 h-3 text-secondary shrink-0 mt-0.5" />
                       <div className="text-on-surface-variant font-mono text-[10px]">
                         {iter.patch_applied}
                       </div>
                     </div>
                   )}
                </div>
              </div>
            )) || <div className="text-outline text-[10px] p-4 text-center">NO_TIMELINE_DATA_RECORDED</div>}
          </div>
        </div>

        {/* Right Panel: Code Comparison */}
        <div className="col-span-8 flex flex-col bg-surface-container-lowest overflow-hidden relative">
          <div className="flex bg-surface-container-high/50 border-b border-outline-variant backdrop-blur-sm">
            <button 
              onClick={() => setTab('original')}
              className={cn(
                "px-8 py-4 mono text-[11px] font-black uppercase transition-all flex items-center gap-2 relative",
                tab === 'original' ? "text-primary" : "text-outline hover:text-on-surface"
              )}
            >
              <FileCode className="w-4 h-4" />
              Original_Payload
              {tab === 'original' && <motion.div layoutId="tab-underline" className="absolute bottom-0 left-0 right-0 h-1 bg-primary" />}
            </button>
            <button 
              onClick={() => setTab('repaired')}
              className={cn(
                "px-8 py-4 mono text-[11px] font-black uppercase transition-all flex items-center gap-2 relative",
                tab === 'repaired' ? "text-secondary" : "text-outline hover:text-on-surface"
              )}
            >
              <Layers className="w-4 h-4" />
              Repaired_Synthesis
              {tab === 'repaired' && <motion.div layoutId="tab-underline" className="absolute bottom-0 left-0 right-0 h-1 bg-secondary" />}
            </button>
            <button 
              onClick={() => setTab('audit')}
              className={cn(
                "px-8 py-4 mono text-[11px] font-black uppercase transition-all flex items-center gap-2 relative",
                tab === 'audit' ? "text-primary" : "text-outline hover:text-on-surface"
              )}
            >
              <Terminal className="w-4 h-4" />
              Technical_Audit
              {tab === 'audit' && <motion.div layoutId="tab-underline" className="absolute bottom-0 left-0 right-0 h-1 bg-primary" />}
            </button>
          </div>
          
          <div className="flex-1 overflow-auto p-0 bg-surface-container-lowest custom-scrollbar font-mono text-[12px] leading-relaxed relative">
            <AnimatePresence mode="wait">
              {tab === 'audit' ? (
                <motion.div
                  key="audit"
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.98 }}
                  className="p-8 space-y-8"
                >
                  <div className="grid grid-cols-2 gap-6">
                    <div className="glassmorphism p-6 rounded-lg">
                      <div className="flex items-center gap-2 mb-4">
                        <Terminal className="w-4 h-4 text-primary" />
                        <span className="font-mono text-[11px] font-black uppercase tracking-widest text-primary">System_Research_Prompt</span>
                      </div>
                      <pre className="text-[11px] text-on-surface-variant bg-transparent overflow-auto max-h-[400px] whitespace-pre-wrap leading-relaxed custom-scrollbar">
                        {submission.iterations?.[selectedIteration]?.ai_prompt || 'AUDIT_DATA_RESTRICTED'}
                      </pre>
                    </div>
                    <div className="glassmorphism p-6 rounded-lg">
                      <div className="flex items-center gap-2 mb-4 text-secondary">
                        <Brain className="w-4 h-4" />
                        <span className="font-mono text-[11px] font-black uppercase tracking-widest">LLM_Logic_Response</span>
                      </div>
                      <pre className="text-[11px] text-on-surface-variant bg-transparent overflow-auto max-h-[400px] whitespace-pre-wrap leading-relaxed custom-scrollbar">
                        {submission.iterations?.[selectedIteration]?.ai_response || 'AUDIT_DATA_RESTRICTED'}
                      </pre>
                    </div>
                  </div>
                  
                  <div className="glassmorphism p-6 rounded-lg relative overflow-hidden">
                    <div className="absolute inset-0 bg-emerald-500/5 mix-blend-overlay"></div>
                    <div className="flex items-center gap-2 mb-4 text-tertiary text-emerald-400 relative z-10">
                      <CheckCircle2 className="w-4 h-4" />
                      <span className="font-mono text-[11px] font-black uppercase tracking-widest">Generated_Pest_Test_Suite</span>
                    </div>
                    <pre className="text-[11px] text-emerald-400/90 bg-transparent overflow-auto max-h-[400px] whitespace-pre-wrap relative z-10 custom-scrollbar">
                      {submission.iterations?.[selectedIteration]?.pest_test_code || 'UNIT_TESTS_NOT_GENERATED'}
                    </pre>
                  </div>

                  <div className="grid grid-cols-3 gap-6">
                     <div className="p-4 bg-surface-container-low border border-outline-variant rounded">
                        <span className="block text-[9px] text-outline uppercase font-bold mb-1">Mutation Score</span>
                        <span className="text-xl font-mono font-black text-secondary">{submission.iterations?.[selectedIteration]?.mutation_score || '0.0'}%</span>
                     </div>
                     <div className="p-4 bg-surface-container-low border border-outline-variant rounded">
                        <span className="block text-[9px] text-outline uppercase font-bold mb-1">Execution Latency</span>
                        <span className="text-xl font-mono font-black text-primary">{submission.iterations?.[selectedIteration]?.duration_ms || '0'}ms</span>
                     </div>
                     <div className="p-4 bg-surface-container-low border border-outline-variant rounded">
                        <span className="block text-[9px] text-outline uppercase font-bold mb-1">Iteration Code ID</span>
                        <span className="text-xl font-mono font-black text-outline">{submission.iterations?.[selectedIteration]?.id?.substring(0,8) || '---'}</span>
                     </div>
                  </div>
                </motion.div>
              ) : (
                <motion.div
                  key={tab}
                  initial={{ opacity: 0, x: tab === 'original' ? -20 : 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: tab === 'original' ? 20 : -20 }}
                  transition={{ duration: 0.2, ease: "easeOut" }}
                  className="min-w-full p-8"
                >
                  <div className="flex gap-6">
                    <div className="text-outline/30 text-right select-none pr-4 border-r border-outline-variant/10 leading-relaxed font-mono text-[10px] w-6">
                      {(tab === 'original' ? submission.original_code : submission.final_code)?.split('\n').map((_, i) => (
                        <div key={i}>{i + 1}</div>
                      ))}
                    </div>
                    <pre className="text-on-surface-variant selection:bg-primary/20 whitespace-pre">
                      {tab === 'original' ? submission.original_code : (submission.final_code || '-- STILL_SYNTHESISING --')}
                    </pre>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            
            {/* Soft HUD Gradient */}
            <div className="absolute inset-0 pointer-events-none bg-gradient-to-t from-surface-container-lowest to-transparent h-20 bottom-0 top-auto opacity-50"></div>
          </div>
          
          <div className="h-12 px-6 bg-surface-container-low border-t border-outline-variant flex items-center justify-between">
            <div className="flex items-center gap-4">
              <span className="mono text-[9px] text-outline font-bold uppercase tracking-widest">Encoding: UTF-8</span>
              <div className="h-3 w-px bg-outline-variant"></div>
              <span className="mono text-[9px] text-outline font-bold uppercase tracking-widest">Final_Mutation_Score: {submission.iterations?.[submission.iterations.length - 1]?.mutation_score || 0}%</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-secondary animate-pulse"></div>
              <span className="mono text-[9px] text-secondary font-bold uppercase">System_Stable</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
