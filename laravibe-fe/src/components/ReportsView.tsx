import React from 'react';
import { ShieldAlert, Cpu, Layers, Activity, BarChart2, CheckCircle2, XCircle } from 'lucide-react';
import { cn } from '../lib/utils';

export const ReportsView: React.FC = () => {
  const [stats, setStats] = React.useState<any>({});
  const [isLoading, setIsLoading] = React.useState(true);

  const fetchStats = async () => {
    setIsLoading(true);
    try {
      const sessionToken = localStorage.getItem('laravibe_session_token');
      const res = await fetch('/api/stats/', { 
        headers: { 'Authorization': `Bearer ${sessionToken}` } 
      });
      if (res.ok) {
        setStats(await res.json());
      }
    } catch (err) {
      console.error('Failed to load stats:', err);
    } finally {
      setIsLoading(false);
    }
  };

  React.useEffect(() => {
    fetchStats();
  }, []);

  return (
    <div className="flex-1 bg-surface-container-lowest p-4 md:p-8 overflow-hidden flex flex-col relative">
      <div className="absolute top-0 left-0 w-full h-1/3 bg-gradient-to-b from-primary/5 to-transparent pointer-events-none"></div>
      
      <div className="max-w-6xl mx-auto h-full flex flex-col relative z-10 w-full">
        {/* Header Block */}
        <div className="mb-10 border-b border-outline-variant pb-6 flex flex-col md:flex-row md:items-end justify-between gap-6">
          <div className="space-y-3">
             <div className="flex items-center gap-2">
               <BarChart2 className="w-4 h-4 text-primary" />
               <span className="font-mono text-[10px] font-black text-primary uppercase tracking-[0.4em]">Analytics_Engine</span>
             </div>
            <h1 className="font-mono text-3xl md:text-4xl font-black tracking-tighter text-on-surface uppercase italic flex items-center gap-4">
              Research_Reports
            </h1>
            <p className="text-on-surface-variant font-mono max-w-2xl text-sm leading-relaxed opacity-70">
              Deep analysis of evaluation runs, thesis research metadata, and distillation metrics.
            </p>
          </div>
          <div className="flex items-center gap-6">
             <div className="bg-surface-container-high px-6 py-3 border border-outline-variant/30 flex flex-col items-end justify-center rounded shadow-md">
                <span className="font-mono text-[9px] font-black text-outline uppercase tracking-widest mb-1">Global_Success_Rate</span>
                <div className="flex items-center gap-3">
                   <Activity className="w-6 h-6 text-secondary" />
                   <span className="text-3xl font-mono font-black text-on-surface leading-none">{stats.global_success_rate?.toFixed(1) || '0.0'}%</span>
                </div>
             </div>
          </div>
        </div>

        <div className="flex-1 flex flex-col overflow-y-auto custom-scrollbar pr-2 pb-12">
            
            <h3 className="font-mono text-sm font-bold text-on-surface mb-4 uppercase tracking-widest border-l-4 border-primary pl-3">Aggregate Distillation</h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
                {[
                  { label: 'Total_Submissions', val: stats.total_submissions || 0, icon: Layers, color: 'text-primary' },
                  { label: 'Avg_Iterations/Run', val: stats.avg_iterations?.toFixed(1) || '0.0', icon: Cpu, color: 'text-secondary' },
                  { label: 'Avg_Mutation_Score', val: stats.avg_mutation_score?.toFixed(1) + '%' || '0%', icon: ShieldAlert, color: 'text-outline' },
                  { label: 'Failed_Submissions', val: stats.total_failed || 0, icon: XCircle, color: 'text-error' },
                ].map((stat, i) => (
                  <div key={i} className="bg-surface-container-low border border-outline-variant/30 p-5 flex flex-col gap-3">
                    <div className="flex items-center gap-2 opacity-60">
                      <stat.icon className="w-4 h-4" />
                      <span className="font-mono text-[10px] font-black uppercase tracking-tighter">{stat.label}</span>
                    </div>
                    <div className={cn("text-3xl font-mono font-black italic", stat.color)}>{stat.val}</div>
                  </div>
                ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
                {/* Trend Graph Placeholder */}
                <div className="lg:col-span-2 bg-surface-container-low border border-outline-variant/30 p-6 flex flex-col min-h-[300px]">
                    <h4 className="font-mono text-xs font-bold text-outline mb-6 uppercase tracking-widest">Mutation_Score_Trend</h4>
                    <div className="flex-1 border-b border-l border-outline-variant/30 relative flex items-end justify-between pb-2 px-2">
                       {/* Mock bars for a trend graph */}
                       {[40, 60, 55, 75, 80, 85, 90, 88, 95, 92, 98, 94].map((h, i) => (
                          <div key={i} className="w-[6%] bg-primary/20 hover:bg-primary transition-colors border border-primary/40 relative group flex items-end" style={{ height: `${h}%` }}>
                             <div className="opacity-0 group-hover:opacity-100 absolute -top-8 left-1/2 -translate-x-1/2 bg-surface p-1 border border-outline-variant text-[10px] font-mono whitespace-nowrap">
                               Score: {h}%
                             </div>
                          </div>
                       ))}
                    </div>
                    <div className="flex justify-between mt-2 font-mono text-[9px] text-outline/50 uppercase">
                       <span>Oldest</span>
                       <span>Recent</span>
                    </div>
                </div>

                {/* Model Distribution */}
                <div className="bg-surface-container-low border border-outline-variant/30 p-6 flex flex-col">
                    <h4 className="font-mono text-xs font-bold text-outline mb-6 uppercase tracking-widest">Model_Utilization</h4>
                    <div className="space-y-4 flex-1">
                       <div className="space-y-1">
                          <div className="flex justify-between font-mono text-[10px] text-on-surface">
                             <span>Qwen3-Max (Dashscope)</span>
                             <span className="text-primary font-bold">65%</span>
                          </div>
                          <div className="w-full bg-surface h-2 border border-outline-variant/30">
                             <div className="bg-primary h-full w-[65%]"></div>
                          </div>
                       </div>
                       <div className="space-y-1">
                          <div className="flex justify-between font-mono text-[10px] text-on-surface">
                             <span>Llama-3.3-70b (Nvidia)</span>
                             <span className="text-secondary font-bold">25%</span>
                          </div>
                          <div className="w-full bg-surface h-2 border border-outline-variant/30">
                             <div className="bg-secondary h-full w-[25%]"></div>
                          </div>
                       </div>
                       <div className="space-y-1">
                          <div className="flex justify-between font-mono text-[10px] text-on-surface">
                             <span>GPT-4o (OpenAI)</span>
                             <span className="text-outline font-bold">10%</span>
                          </div>
                          <div className="w-full bg-surface h-2 border border-outline-variant/30">
                             <div className="bg-outline h-full w-[10%]"></div>
                          </div>
                       </div>
                    </div>
                    <div className="mt-4 pt-4 border-t border-outline-variant/30 flex items-center gap-2">
                       <CheckCircle2 className="w-3 h-3 text-secondary" />
                       <span className="font-mono text-[10px] text-outline">Load balancing optimal</span>
                    </div>
                </div>
            </div>
        </div>
      </div>
    </div>
  );
};
