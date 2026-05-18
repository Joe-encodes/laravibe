import React from 'react';
import { ShieldAlert, Cpu, Layers, Activity, BarChart2, CheckCircle2, XCircle, RefreshCw } from 'lucide-react';
import { cn } from '../lib/utils';

const COLORS = ['text-primary', 'text-secondary', 'text-indigo-400', 'text-amber-400', 'text-rose-400'];
const BAR_COLORS = ['bg-primary', 'bg-secondary', 'bg-indigo-400', 'bg-amber-400', 'bg-rose-400'];

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

  const modelUtilization: { model: string; count: number; pct: number }[] = stats.model_utilization || [];
  const mutationTrend: { score: number; label: string }[] = stats.mutation_trend || [];
  const maxTrend = mutationTrend.length > 0 ? Math.max(...mutationTrend.map(t => t.score)) : 100;

  return (
    <div className="flex-1 bg-surface-container-lowest p-6 overflow-hidden flex flex-col relative">
      <div className="absolute top-0 left-0 w-full h-1/3 bg-gradient-to-b from-primary/5 to-transparent pointer-events-none"></div>
      
      <div className="max-w-6xl mx-auto h-full flex flex-col relative z-10 w-full">
        {/* Header Block */}
        <div className="mb-8 border-b border-outline-variant pb-6 flex flex-col md:flex-row md:items-end justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <BarChart2 className="w-4 h-4 text-primary" />
              <span className="text-hud text-primary">ANALYTICS_ENGINE</span>
            </div>
            <h1 className="font-mono text-3xl font-black tracking-tighter text-on-surface uppercase italic">
              Research_Reports
            </h1>
            <p className="text-on-surface-variant text-sm max-w-2xl opacity-70">
              Deep analysis of evaluation runs, thesis research metadata, and distillation metrics.
            </p>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={fetchStats}
              disabled={isLoading}
              className="flex items-center gap-2 px-4 py-2 bg-surface-container-high border border-outline-variant rounded text-hud text-on-surface-variant hover:border-primary hover:text-primary transition-all"
            >
              <RefreshCw className={cn("w-3 h-3", isLoading && "animate-spin")} />
              REFRESH
            </button>
            <div className="bg-surface-container-high px-6 py-3 border border-outline-variant/30 flex flex-col items-end justify-center rounded shadow-md">
              <span className="text-hud text-outline mb-1">GLOBAL_SUCCESS_RATE</span>
              <div className="flex items-center gap-3">
                <Activity className="w-6 h-6 text-secondary" />
                <span className="text-3xl font-mono font-black text-on-surface leading-none">
                  {isLoading ? '—' : `${stats.global_success_rate?.toFixed(1) || '0.0'}%`}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex-1 flex flex-col overflow-y-auto custom-scrollbar pr-2 pb-12 gap-8">
          
          {/* Aggregate Bento */}
          <div>
            <h3 className="text-hud text-on-surface mb-4 border-l-4 border-primary pl-3">AGGREGATE_DISTILLATION</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: 'TOTAL_SUBMISSIONS', val: isLoading ? '—' : (stats.total_submissions || 0), icon: Layers, color: 'text-primary' },
                { label: 'AVG_ITERATIONS/RUN', val: isLoading ? '—' : (stats.avg_iterations?.toFixed(1) || '0.0'), icon: Cpu, color: 'text-secondary' },
                { label: 'AVG_MUTATION_SCORE', val: isLoading ? '—' : `${stats.avg_mutation_score?.toFixed(1) || '0'}%`, icon: ShieldAlert, color: 'text-indigo-400' },
                { label: 'FAILED_SUBMISSIONS', val: isLoading ? '—' : (stats.total_failed || 0), icon: XCircle, color: 'text-error' },
              ].map((stat, i) => (
                <div key={i} className="bg-surface-container-low border border-outline-variant/30 p-5 flex flex-col gap-3 hover:border-outline-variant transition-colors">
                  <div className="flex items-center gap-2 opacity-60">
                    <stat.icon className="w-4 h-4" />
                    <span className="text-hud">{stat.label}</span>
                  </div>
                  <div className={cn("text-3xl font-mono font-black italic", stat.color)}>{stat.val}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Mutation Score Trend — real data */}
            <div className="lg:col-span-2 bg-surface-container-low border border-outline-variant/30 p-6 flex flex-col min-h-[280px]">
              <div className="flex items-center justify-between mb-6">
                <h4 className="text-hud text-outline">MUTATION_SCORE_TREND</h4>
                <span className="text-hud text-outline/50">{mutationTrend.length} RECORDS</span>
              </div>

              {isLoading ? (
                <div className="flex-1 flex items-center justify-center opacity-30">
                  <RefreshCw className="w-8 h-8 animate-spin text-primary" />
                </div>
              ) : mutationTrend.length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center opacity-30 gap-2">
                  <ShieldAlert className="w-8 h-8 text-primary" />
                  <p className="text-log">No mutation data yet — run a repair to populate</p>
                </div>
              ) : (
                <>
                  <div className="flex-1 border-b border-l border-outline-variant/30 relative flex items-end justify-between pb-2 px-1 gap-0.5">
                    {mutationTrend.map((t, i) => {
                      const h = maxTrend > 0 ? (t.score / maxTrend) * 100 : 0;
                      const isHigh = t.score >= 80;
                      return (
                        <div
                          key={i}
                          className={cn(
                            "flex-1 min-w-[6px] transition-colors border relative group flex items-end",
                            isHigh
                              ? "bg-secondary/30 hover:bg-secondary border-secondary/40"
                              : "bg-primary/20 hover:bg-primary border-primary/40"
                          )}
                          style={{ height: `${Math.max(h, 4)}%` }}
                        >
                          <div className="opacity-0 group-hover:opacity-100 absolute -top-9 left-1/2 -translate-x-1/2 bg-surface-container-high p-1.5 border border-outline-variant text-hud whitespace-nowrap z-10 rounded shadow-lg">
                            {t.label}: {t.score}%
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex justify-between mt-2">
                    <span className="text-hud text-outline/50">OLDEST</span>
                    <span className="text-hud text-outline/50">RECENT</span>
                  </div>
                </>
              )}
            </div>

            {/* Model Utilization — real data */}
            <div className="bg-surface-container-low border border-outline-variant/30 p-6 flex flex-col">
              <h4 className="text-hud text-outline mb-6">MODEL_UTILIZATION</h4>

              {isLoading ? (
                <div className="flex-1 flex items-center justify-center opacity-30">
                  <RefreshCw className="w-6 h-6 animate-spin text-primary" />
                </div>
              ) : modelUtilization.length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center opacity-30 gap-2">
                  <Cpu className="w-8 h-8 text-primary" />
                  <p className="text-log text-center">No model data yet</p>
                </div>
              ) : (
                <div className="space-y-4 flex-1">
                  {modelUtilization.slice(0, 5).map((m, i) => (
                    <div key={i} className="space-y-1.5">
                      <div className="flex justify-between items-center">
                        <span className="text-log text-on-surface truncate max-w-[70%]">{m.model}</span>
                        <span className={cn("text-hud font-bold", COLORS[i % COLORS.length])}>{m.pct}%</span>
                      </div>
                      <div className="w-full bg-surface h-1.5 border border-outline-variant/30 rounded-full overflow-hidden">
                        <div
                          className={cn("h-full rounded-full transition-all duration-1000", BAR_COLORS[i % BAR_COLORS.length])}
                          style={{ width: `${m.pct}%` }}
                        />
                      </div>
                      <span className="text-hud text-outline/40">{m.count} iterations</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-4 pt-4 border-t border-outline-variant/30 flex items-center gap-2">
                <CheckCircle2 className="w-3 h-3 text-secondary" />
                <span className="text-hud text-outline">
                  {modelUtilization.length > 0 ? `${modelUtilization.length} ACTIVE_MODELS` : 'AWAITING_DATA'}
                </span>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
};
