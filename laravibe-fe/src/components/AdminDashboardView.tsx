import React from 'react';
import { Database, ShieldAlert, Cpu, Layers, Layout, ChevronRight, Activity, Terminal } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { MASTER_REPAIR_TOKEN } from '../constants';

export const AdminDashboardView: React.FC = () => {
  const navigate = useNavigate();
  const [datasets, setDatasets] = React.useState<any[]>([]);
  const [evaluations, setEvaluations] = React.useState<any[]>([]);
  const [stats, setStats] = React.useState<any>({});
  const [activeExpId, setActiveExpId] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [isEvaluating, setIsEvaluating] = React.useState(false);

  const fetchData = async () => {
    setIsLoading(true);
    try {
      const sessionToken = localStorage.getItem('laravibe_session_token');
      const authHeaders = {
        'Authorization': `Bearer ${sessionToken}`
      };
      const [dsRes, evalRes, statsRes] = await Promise.all([
        fetch('/api/admin/training-dataset', { headers: authHeaders }),
        fetch('/api/admin/evaluations', { headers: authHeaders }),
        fetch('/api/stats/', { headers: authHeaders })
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
        const sessionToken = localStorage.getItem('laravibe_session_token');
        const authHeaders = {
          'Authorization': `Bearer ${sessionToken}`
        };
        const [evalRes, statsRes] = await Promise.all([
          fetch('/api/admin/evaluations', { headers: authHeaders }),
          fetch('/api/stats/', { headers: authHeaders })
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
      const sessionToken = localStorage.getItem('laravibe_session_token');
      const res = await fetch('/api/evaluate', { 
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${sessionToken}`
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
            <p className="text-on-surface-variant font-mono max-w-2xl text-sm leading-relaxed opacity-70">
              Unified interface for thesis research metadata, automated batch evaluations, and training data distillation.
            </p>
          </div>
          <div className="flex items-center gap-6">
             <button 
               onClick={handleRunBatch}
               disabled={isEvaluating}
               className="bg-primary/20 hover:bg-primary/30 text-primary border border-primary/40 px-8 py-4 mono text-xs font-black uppercase tracking-widest transition-all rounded shadow-md"
             >
               {isEvaluating ? 'Executing_Evaluation...' : 'Run_Batch_Sync'}
             </button>
             <div className="bg-surface-container-high px-6 py-3 border-2 border-primary/20 flex flex-col items-end justify-center rounded shadow-md">
                <span className="mono text-[9px] font-black text-outline uppercase tracking-widest mb-1">Global_Accuracy</span>
                <div className="flex items-center gap-3">
                   <Activity className="w-6 h-6 text-secondary" />
                   <span className="text-3xl font-mono font-black text-on-surface leading-none">{stats.global_success_rate?.toFixed(1) || 0}%</span>
                </div>
             </div>
          </div>
        </div>


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
                                 <button 
                                    onClick={() => navigate('/history')}
                                    className="text-primary font-mono text-[11px] font-black uppercase tracking-widest hover:underline group-hover:translate-x-1 transition-transform inline-flex items-center gap-2"
                                 >
                                    View_Report <ChevronRight className="w-3 h-3" />
                                 </button>
                              </td>
                          </tr>
                       ))}
                    </tbody>
                 </table>
              </div>
           </div>
      </div>
    </div>
  );
};
