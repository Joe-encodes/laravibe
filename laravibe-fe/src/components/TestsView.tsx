import React from 'react';
import { useParams } from 'react-router-dom';
import { CheckCircle2, XCircle, Play, Database, Zap, ShieldCheck, Terminal, Activity, Search } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { MASTER_REPAIR_TOKEN } from '../constants';

export const TestsView: React.FC = () => {
  const { submissionId } = useParams<{ submissionId: string }>();
  const [submission, setSubmission] = React.useState<any>(null);
  const [isLoading, setIsLoading] = React.useState(true);

  React.useEffect(() => {
    if (!submissionId) return;
    const load = async () => {
      console.info('[LaraVibe] Loading test results...', { submissionId });
      try {
        const sessionToken = localStorage.getItem('laravibe_session_token');
        const res = await fetch(`/api/repair/${submissionId}`, {
          headers: {
            'Authorization': `Bearer ${sessionToken}`
          }
        });
        console.info('[LaraVibe] Repair API Response:', { status: res.status });
        const data = await res.json();
        console.info('[LaraVibe] Data retrieved:', { iterations: data.iterations?.length });
        setSubmission(data);
      } catch (err) {
        console.error(err);
      } finally {
        setIsLoading(false);
      }
    };
    load();
  }, [submissionId]);

  return (
    <div className="flex-1 flex flex-col bg-surface-container-lowest overflow-hidden relative">
      {/* Grid Pattern BG */}
      <div className="absolute inset-0 bg-[radial-gradient(#1e293b_1px,transparent_1px)] [background-size:24px_24px] opacity-10 pointer-events-none"></div>

      {/* Header Block */}
      <div className="p-8 border-b border-outline-variant bg-surface-container-low relative z-10">
        <div className="flex justify-between items-end">
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-5 h-5 text-secondary" />
              <span className="mono text-[10px] font-black text-secondary uppercase tracking-[0.4em]">Test_Orchestrator_v3</span>
            </div>
            <h1 className="text-4xl font-mono font-black text-on-surface tracking-tighter uppercase italic leading-none">
              Validation_Suite_Execution
            </h1>
            <p className="text-on-surface-variant max-w-xl text-sm leading-relaxed font-mono opacity-70">
              Running high-fidelity Pest 3 tests against synthesized patches. Each assertion is verified within an isolated sandbox kernel.
            </p>
          </div>
          <div className="flex items-center gap-6">
             <div className="text-right">
               <div className="text-2xl font-mono font-black text-on-surface">{submission?.iterations?.length || 0}</div>
               <div className="mono text-[9px] font-bold text-outline uppercase">Pass_Cycles</div>
             </div>
             <div className="h-10 w-px bg-outline-variant/30"></div>
             <div className="text-right">
               <div className="text-2xl font-mono font-black text-secondary">ACTIVE</div>
               <div className="mono text-[9px] font-bold text-outline uppercase">Kernel_Status</div>
             </div>
          </div>
        </div>
      </div>

      <div className="flex-1 grid grid-cols-12 overflow-hidden relative z-10">
        {/* Left: Test List */}
        <div className="col-span-8 border-r border-outline-variant overflow-y-auto custom-scrollbar p-8 space-y-6 pb-24">
          <div className="flex items-center justify-between mb-8">
            <div className="flex items-center gap-3">
               <div className="w-1.5 h-1.5 rounded-full bg-secondary animate-ping"></div>
               <span className="mono text-xs font-black text-on-surface uppercase tracking-[0.2em]">Pest_Validation_Outputs</span>
            </div>
            <div className="flex items-center gap-2 bg-surface-container-high px-3 py-1.5 border border-outline-variant/30 rounded-sm">
              <Search className="w-3.5 h-3.5 text-outline" />
              <span className="mono text-[9px] font-black text-outline uppercase">Streaming_Feed</span>
            </div>
          </div>

          <AnimatePresence>
            {isLoading ? (
               <div className="mono text-xs font-bold text-primary animate-pulse py-12 text-center">LINKING_TO_KERNEL_STREAM...</div>
            ) : (
              submission?.iterations?.map((iter: any, i: number) => (
                <motion.div 
                  key={iter.id} 
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: i * 0.1 }}
                  className="flex flex-col p-6 bg-surface-container-low border-2 border-outline-variant/50 group transition-all hover:border-secondary/30 relative overflow-hidden"
                >
                  {/* Subtle index badge */}
                  <span className="absolute top-2 right-4 mono text-[14px] font-black text-outline/5 select-none">{i+1}</span>

                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-4">
                      {iter.pest_test_result?.includes('FAIL') ? (
                        <div className="p-2 bg-error/10 border border-error/20 rounded">
                           <XCircle className="w-6 h-6 text-error" />
                        </div>
                      ) : (
                        <div className="p-2 bg-secondary/10 border border-secondary/20 rounded">
                           <CheckCircle2 className="w-6 h-6 text-secondary" />
                        </div>
                      )}
                      <div>
                        <div className="mono text-sm font-black text-on-surface uppercase italic">Iteration_{iter.iteration_num}_Execution</div>
                        <div className="text-[10px] text-outline font-bold uppercase tracking-widest mt-0.5 opacity-60">Sequence_Module: PHP_PEST_CONTRACT</div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="mono text-xs font-black text-on-surface">{iter.duration_ms}ms</div>
                      <div className={cn(
                        "text-[10px] font-black uppercase tracking-tighter",
                        iter.pest_test_result?.includes('FAIL') ? "text-error" : "text-secondary"
                      )}>
                        {iter.status}
                      </div>
                    </div>
                  </div>
                  {iter.pest_test_result && (
                    <div className="mt-4 p-4 bg-black/40 border border-outline-variant/20 rounded-sm font-mono text-[10px] leading-relaxed group-hover:border-secondary/20 transition-colors">
                       <div className="flex justify-between items-center mb-2 border-b border-outline-variant/10 pb-2">
                         <span className="text-outline uppercase font-black text-[9px]">Raw_Buffer_Output</span>
                         <Terminal className="w-3 h-3 text-outline/30" />
                       </div>
                       <pre className="text-on-surface-variant whitespace-pre-wrap max-h-40 overflow-y-auto custom-scrollbar-thin">
                         {iter.pest_test_result}
                       </pre>
                    </div>
                  )}
                </motion.div>
              )) || <div className="text-outline text-xs font-mono p-12 text-center">NO_SEQUENCE_ARTIFACTS_SYNCHRONISED</div>
            )}
          </AnimatePresence>
        </div>

        {/* Right: Learning & Performance Gate */}
        <div className="col-span-4 bg-surface-container-low border-l border-outline-variant p-8 flex flex-col gap-10">
          <div>
            <div className="flex items-center gap-3 mb-6">
              <Activity className="w-5 h-5 text-primary" />
              <h2 className="mono text-xs font-black text-on-surface uppercase tracking-[.25em]">Quality_Gate_Metrics</h2>
            </div>
            <div className="space-y-6">
              {[
                { label: 'Mutation_Hardening', level: submission?.iterations?.[submission.iterations.length - 1]?.mutation_score || 0, icon: Zap, color: 'bg-primary' },
                { label: 'Logic_Evolution', level: Math.min((submission?.iterations?.length || 0) * 15, 100), icon: Activity, color: 'bg-secondary' },
                { label: 'Kernel_Stability', level: submission?.status === 'success' ? 100 : 0, icon: Database, color: 'bg-primary' },
              ].map((node, i) => (
                <div key={i} className="group">
                  <div className="flex justify-between text-[10px] font-mono font-black uppercase mb-2 tracking-tighter">
                    <div className="flex items-center gap-2">
                      <node.icon className="w-3 h-3 text-outline group-hover:text-on-surface transition-colors" />
                      <span>{node.label}</span>
                    </div>
                    <span className="text-on-surface">{node.level}%</span>
                  </div>
                  <div className="h-1 bg-surface-container-highest w-full overflow-hidden rounded-full">
                    <motion.div 
                      initial={{ width: 0 }}
                      animate={{ width: `${node.level}%` }}
                      transition={{ duration: 1.5, ease: "easeOut" }}
                      className={cn("h-full transition-all duration-1000", node.color)}
                    ></motion.div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-auto bg-surface-container-high p-4 border border-outline-variant/30 rounded-sm italic">
             <p className="text-[10px] text-on-surface-variant leading-relaxed">
               "Automated synthesis verified. The mutation score reflects the patch's resilience against semantic alterations and logic drift."
             </p>
          </div>
        </div>
      </div>
    </div>
  );
};
