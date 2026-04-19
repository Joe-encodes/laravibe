import React from 'react';
import { Database, ShieldAlert, Cpu, Layers, Layout, ChevronRight, Activity, Terminal } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { MASTER_REPAIR_TOKEN } from '../constants';

export const AdminDashboardView: React.FC = () => {
  const [datasets, setDatasets] = React.useState<any[]>([]);
  const [evaluations, setEvaluations] = React.useState<any[]>([]);
  const [stats, setStats] = React.useState<any>({});
  const [activeExpId, setActiveExpId] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [isEvaluating, setIsEvaluating] = React.useState(false);
  const [activeTab, setActiveTab] = React.useState<'vault' | 'hub'>('hub');

  const fetchData = async () => {
    setIsLoading(true);
    try {
      const authHeaders = {
        'Authorization': `Bearer ${MASTER_REPAIR_TOKEN}`
      };
      const [dsRes, evalRes, statsRes] = await Promise.all([
        fetch('/api/admin/training-dataset', { headers: authHeaders }),
        fetch('/api/admin/evaluations', { headers: authHeaders }),
        fetch('/api/stats', { headers: authHeaders })
      ]);
      if (dsRes.ok) setDatasets((await dsRes.json()).data);
      if (evalRes.ok) setEvaluations(await evalRes.json());
      if (statsRes.ok) setStats(await statsRes.json());
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
    } finally {
      setIsLoading(false);
    }
  };

  React.useEffect(() => {
    fetchData();
  }, []);

  // Polling for experiment status
  React.useEffect(() => {
    let interval: any;
    if (isEvaluating) {
      interval = setInterval(async () => {
        const authHeaders = {
          'Authorization': `Bearer ${MASTER_REPAIR_TOKEN}`
        };
        const [evalRes, statsRes] = await Promise.all([
          fetch('/api/admin/evaluations', { headers: authHeaders }),
          fetch('/api/stats', { headers: authHeaders })
        ]);
        if (evalRes.ok) {
           const evals = await evalRes.json();
           setEvaluations(evals);
           // If the active experiment ID is no longer 'running' in the backend evaluation_results (logic simplified)
           // we would stop polling. For now we poll while the UI state isEvaluating is true.
        }
        if (statsRes.ok) setStats(await statsRes.json());
      }, 5000);
    }
    return () => clearInterval(interval);
  }, [isEvaluating]);

  const handleRunBatch = async () => {
    setIsEvaluating(true);
    try {
      const res = await fetch('/api/evaluate', { 
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${MASTER_REPAIR_TOKEN}`
        }
      });
      const data = await res.json();
      setActiveExpId(data.experiment_id);
      fetchData();
    } catch (e) {
      console.error('Failed to start evaluation:', e);
      setIsEvaluating(false);
    }
  };

  return (
    <div className="flex-1 bg-surface-container-lowest p-8 overflow-hidden flex flex-col relative">
      {/* Background HUD Accents */}
      <div className="absolute top-0 right-0 w-1/2 h-full bg-gradient-to-l from-primary/5 to-transparent pointer-events-none"></div>
      
      <div className="max-w-6xl mx-auto h-full flex flex-col relative z-10 w-full">
        {/* Header Block */}
        <div className="mb-10 border-b border-outline-variant pb-6 flex items-end justify-between">
          <div className="space-y-3">
             <div className="flex items-center gap-2">
               <ShieldAlert className="w-4 h-4 text-primary" />
               <span className="mono text-[10px] font-black text-primary uppercase tracking-[0.4em]">Administrative_Override</span>
             </div>
            <h1 className="font-mono text-4xl font-black tracking-tighter text-on-surface uppercase italic flex items-center gap-4">
              Research_Hub
              <div className={cn("h-2 w-2 rounded-full", isEvaluating ? "bg-primary animate-ping" : "bg-secondary animate-pulse shadow-[0_0_10px_rgba(78,222,163,0.5)]")}></div>
            </h1>
            <p className="text-on-surface-variant font-sans max-w-2xl text-sm leading-relaxed opacity-70">
              Unified interface for thesis research metadata, automated batch evaluations, and training data distillation.
            </p>
          </div>
          <div className="flex gap-4">
             <button 
               onClick={handleRunBatch}
               disabled={isEvaluating}
               className="bg-primary/20 hover:bg-primary/30 text-primary border border-primary/40 px-6 py-2 mono text-xs font-black uppercase tracking-widest transition-all"
             >
               {isEvaluating ? 'Executing_Evaluation...' : 'Run_Batch_Sync'}
             </button>
             <div className="bg-surface-container-high px-6 py-3 border-2 border-primary/20 flex flex-col items-end gap-1">
                <span className="mono text-[9px] font-black text-outline uppercase tracking-widest">Global_Accuracy</span>
                <div className="flex items-center gap-3">
                   <Activity className="w-5 h-5 text-secondary" />
                   <span className="text-2xl font-mono font-black text-on-surface">{stats.global_success_rate?.toFixed(1) || 0}%</span>
                </div>
             </div>
          </div>
        </div>

        {/* Tab System */}
        <div className="flex gap-8 mb-8 border-b border-outline-variant/30">
          <button 
            onClick={() => setActiveTab('hub')}
            className={cn(
              "pb-4 mono text-xs font-black uppercase tracking-[0.2em] relative transition-all",
              activeTab === 'hub' ? "text-primary" : "text-outline hover:text-on-surface"
            )}
          >
            Evaluation_Hub
            {activeTab === 'hub' && <motion.div layoutId="adm-tab" className="absolute bottom-0 left-0 right-0 h-1 bg-primary" />}
          </button>
          <button 
            onClick={() => setActiveTab('vault')}
            className={cn(
              "pb-4 mono text-xs font-black uppercase tracking-[0.2em] relative transition-all",
              activeTab === 'vault' ? "text-secondary" : "text-outline hover:text-on-surface"
            )}
          >
            Training_Vault
            {activeTab === 'vault' && <motion.div layoutId="adm-tab" className="absolute bottom-0 left-0 right-0 h-1 bg-secondary" />}
          </button>
        </div>

        {activeTab === 'hub' ? (
           <div className="flex-1 flex flex-col overflow-hidden">
              <div className="grid grid-cols-4 gap-4 mb-8">
                 {[
                   { label: 'Total_Experiments', val: evaluations.length.toString(), icon: Layers, color: 'text-primary' },
                   { label: 'Last_Success_Rate', val: evaluations[0]?.success_rate_pct?.toFixed(1) + '%' || '---', icon: Activity, color: 'text-secondary' },
                   { label: 'Avg_Iterations', val: stats.avg_iterations?.toFixed(1) || '0.0', icon: Cpu, color: 'text-primary' },
                   { label: 'Mutation_Average', val: stats.avg_mutation_score?.toFixed(1) + '%' || '0%', icon: ShieldAlert, color: 'text-secondary' },
                 ].map((stat, i) => (
                   <div key={i} className="bg-surface-container-low border border-outline-variant/30 p-4 flex flex-col gap-2">
                      <div className="flex items-center gap-2 opacity-50">
                        <stat.icon className="w-3 h-3" />
                        <span className="mono text-[9px] font-black uppercase tracking-tighter">{stat.label}</span>
                      </div>
                      <div className={cn("text-xl font-mono font-black italic", stat.color)}>{stat.val}</div>
                   </div>
                 ))}
              </div>
              
              <div className="flex-1 overflow-y-auto custom-scrollbar bg-surface-container-low/30 border border-outline-variant/20 rounded-md">
                 <table className="w-full text-left border-collapse">
                    <thead className="sticky top-0 bg-surface-container-high z-10">
                       <tr className="border-b border-outline-variant">
                          <th className="p-4 mono text-[10px] text-outline uppercase font-black">Experiment_ID</th>
                          <th className="p-4 mono text-[10px] text-outline uppercase font-black">Cases</th>
                          <th className="p-4 mono text-[10px] text-outline uppercase font-black">Success_Rate</th>
                          <th className="p-4 mono text-[10px] text-outline uppercase font-black">Date</th>
                          <th className="p-4 mono text-[10px] text-outline uppercase font-black">Action</th>
                       </tr>
                    </thead>
                    <tbody>
                       {evaluations.map((ev, i) => (
                          <tr key={ev.id} className="border-b border-outline-variant/30 hover:bg-primary/5 transition-colors group">
                             <td className="p-4 font-mono text-xs text-on-surface">{ev.id}</td>
                             <td className="p-4 font-mono text-xs text-on-surface">{ev.cases?.length || 0}</td>
                             <td className="p-4 font-mono text-xs text-secondary font-bold">{ev.success_rate_pct?.toFixed(1)}%</td>
                             <td className="p-4 font-mono text-[10px] text-outline">{new Date(ev.created_at).toLocaleString()}</td>
                             <td className="p-4">
                                <button className="text-primary mono text-[10px] font-black uppercase tracking-widest hover:underline group-hover:translate-x-1 transition-transform inline-flex items-center gap-2">
                                   View_Report <ChevronRight className="w-3 h-3" />
                                </button>
                             </td>
                          </tr>
                       ))}
                    </tbody>
                 </table>
              </div>
           </div>
        ) : (
           <div className="flex-1 overflow-y-auto custom-scrollbar pr-4 pb-20">
             <AnimatePresence>
               {isLoading ? (
                 <div className="flex flex-col items-center justify-center py-20 gap-4 opacity-50">
                   <div className="w-12 h-1 bg-primary animate-pulse"></div>
                   <span className="mono text-xs font-black uppercase tracking-[0.5em]">Synchronizing_Vault...</span>
                 </div>
               ) : datasets.length === 0 ? (
                 <div className="flex flex-col items-center justify-center py-20 gap-6 border-2 border-dashed border-outline-variant/20">
                   <Layers className="w-16 h-16 text-outline/30" />
                   <div className="text-center space-y-2">
                     <h3 className="mono text-sm font-black text-on-surface uppercase italic">Vault_Empty</h3>
                     <p className="max-w-xs text-[10px] text-outline uppercase font-bold tracking-widest leading-relaxed"> No successful synthesis cycles recorded. Initiate repair operations to populate. </p>
                   </div>
                 </div>
               ) : (
                  <div className="grid grid-cols-2 gap-6">
                    {datasets.map((item, i) => (
                     <motion.div 
                       key={item.id} 
                       initial={{ opacity: 0, y: 20 }}
                       animate={{ opacity: 1, y: 0 }}
                       transition={{ delay: i * 0.1 }}
                       className="bg-surface-container-low border border-outline-variant/50 hover:border-primary/50 transition-all flex flex-col h-[400px] group shadow-xl hover:shadow-primary/5"
                     >
                       <div className="h-10 bg-surface-container-high border-b border-outline-variant flex items-center justify-between px-4">
                         <div className="flex items-center gap-3">
                           <div className="w-2 h-2 rounded-full bg-secondary"></div>
                           <span className="text-[10px] uppercase font-black text-on-surface-variant font-mono tracking-widest">Entry_{item.id.substring(0, 8)}</span>
                         </div>
                         <div className="flex items-center gap-4">
                           <span className="text-[10px] uppercase font-black text-primary font-mono">{item.iterations} CYCLES</span>
                           <ChevronRight className="w-4 h-4 text-outline group-hover:translate-x-1 transition-transform" />
                         </div>
                       </div>
                       <div className="flex-1 grid grid-cols-2 overflow-hidden bg-surface-container-lowest">
                         <div className="p-4 border-r border-outline-variant flex flex-col">
                           <span className="text-[9px] uppercase font-bold text-error/60 mb-3 tracking-[0.2em] font-mono">BROKEN_INPUT</span>
                           <div className="flex-1 overflow-auto custom-scrollbar-thin bg-black/20 p-2 rounded-sm">
                             <pre className="text-[8px] font-mono whitespace-pre text-outline/80 leading-tight">
                               {item.original_code}
                             </pre>
                           </div>
                         </div>
                         <div className="p-4 flex flex-col bg-secondary/5">
                           <span className="text-[9px] uppercase font-bold text-secondary mb-3 tracking-[0.2em] font-mono">OPTIMISED_PATCH</span>
                           <div className="flex-1 overflow-auto custom-scrollbar-thin bg-black/20 p-2 rounded-sm">
                             <pre className="text-[8px] font-mono whitespace-pre text-primary leading-tight">
                               {item.final_code}
                             </pre>
                           </div>
                         </div>
                       </div>
                       <div className="h-8 border-t border-outline-variant/30 flex items-center px-4 justify-between">
                          <span className="text-[8px] mono font-bold text-outline">Category: {item.category || 'REPAIR'}</span>
                          <span className="text-[8px] mono font-bold text-outline-variant italic">{new Date(item.created_at).toLocaleDateString()}</span>
                       </div>
                     </motion.div>
                   ))}
                  </div>
               )}
             </AnimatePresence>
           </div>
        )}
      </div>
    </div>
  );
};
