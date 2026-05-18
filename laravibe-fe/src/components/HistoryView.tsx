import React from 'react';
import { useNavigate } from 'react-router-dom';
import { History, Search, ChevronRight, Zap, Shield, Cpu, Activity } from 'lucide-react';
import { cn } from '../lib/utils';

export const HistoryView: React.FC = () => {
  const navigate = useNavigate();
  const [historyItems, setHistoryItems] = React.useState<any[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [searchQuery, setSearchQuery] = React.useState('');
  const [page, setPage] = React.useState(0);
  const [stats, setStats] = React.useState<any>({});
  const limit = 20;

  const fetchHistory = async (currentPage: number) => {
    setIsLoading(true);
    try {
      const skip = currentPage * limit;
      const sessionToken = localStorage.getItem('laravibe_session_token');
      const [historyRes, statsRes] = await Promise.all([
        fetch(`/api/history?skip=${skip}&limit=${limit}`, { headers: { 'Authorization': `Bearer ${sessionToken}` } }),
        fetch('/api/stats/', { headers: { 'Authorization': `Bearer ${sessionToken}` } })
      ]);
      if (!historyRes.ok) throw new Error('API Error');
      const data = await historyRes.json();
      if (statsRes.ok) setStats(await statsRes.json());
      
      const mapped = data.map((sub: any) => ({
        id: sub.id,
        title: `Repair #${sub.id.substring(0, 8)}`,
        codeSnippet: `${sub.total_iterations} iterations`,
        status: sub.status === 'success' ? 'COMMITTED' : (sub.status === 'running' ? 'ACTIVE' : 'FAILED'),
        date: new Date(sub.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        fullDate: new Date(sub.created_at).toLocaleDateString(),
        category: sub.category || 'GENERAL',
        userPrompt: sub.user_prompt
      }));
      setHistoryItems(mapped);
    } catch (err) {
      console.error('Failed to load history:', err);
    } finally {
      setIsLoading(false);
    }
  };

  React.useEffect(() => {
    fetchHistory(page);
  }, [page]);

  const filteredHistory = historyItems.filter(item => 
    item.id.toLowerCase().includes(searchQuery.toLowerCase()) || 
    item.status.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex-1 bg-surface-container-lowest p-6 overflow-hidden flex flex-col relative">
      <div className="absolute top-0 right-0 w-1/2 h-full bg-gradient-to-l from-primary/5 to-transparent pointer-events-none"></div>
      
      <div className="max-w-6xl mx-auto h-full flex flex-col relative z-10 w-full">
        {/* Header Block */}
        <div className="mb-8 border-b border-outline-variant pb-6 flex flex-col md:flex-row md:items-end justify-between gap-6">
          <div className="space-y-2">
             <div className="flex items-center gap-2">
               <History className="w-4 h-4 text-primary" />
               <span className="text-hud text-primary">OPERATIONAL_ARCHIVES</span>
             </div>
            <h1 className="font-mono text-3xl font-black tracking-tighter text-on-surface uppercase italic">
              Repair_History
            </h1>
            <p className="text-on-surface-variant text-sm max-w-2xl opacity-70">
              Browse the latest synthesized patches and diagnostic history. Every iteration is logged for audit visibility.
            </p>
          </div>
          <div className="flex flex-col items-end gap-4 w-full md:w-auto">
             <div className="flex items-center w-full md:w-auto gap-4 bg-surface-container-high border border-outline-variant/30 px-4 py-2 rounded-sm backdrop-blur-md">
                <Search className="w-4 h-4 text-outline" />
                <input 
                  type="text" 
                  placeholder="Filter archives..." 
                  className="bg-transparent outline-none text-sm text-on-surface w-full md:w-48 font-mono"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
             </div>
          </div>
        </div>

        <div className="flex-1 flex flex-col overflow-hidden">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8 shrink-0">
                {[
                  { label: 'Total_Repairs', val: stats.total_submissions?.toString() || '0', icon: Activity, color: 'text-primary' },
                  { label: 'Global_Success', val: stats.global_success_rate?.toFixed(1) + '%' || '0.0%', icon: Zap, color: 'text-secondary' },
                  { label: 'Mutation_Avg', val: (stats.mutation_average || 0).toFixed(1) + '%', icon: Shield, color: 'text-outline' },
                  { label: 'Avg_Latency', val: (stats.average_duration || 0).toFixed(0) + 'ms', icon: Cpu, color: 'text-outline' }
                ].map((stat, i) => (
                  <div key={i} className="bg-surface-container-low border border-outline-variant/30 p-4 flex flex-col gap-2">
                    <div className="flex items-center gap-2 opacity-50">
                      <stat.icon className="w-3 h-3" />
                      <span className="font-mono text-[9px] font-black uppercase tracking-tighter">{stat.label}</span>
                    </div>
                    <div className={cn("text-xl font-mono font-black italic", stat.color)}>{stat.val}</div>
                  </div>
                ))}
            </div>
            
            <div className="flex-1 flex flex-col bg-surface-container-low/30 rounded-md overflow-hidden">
                <div className="flex-1 overflow-y-auto custom-scrollbar pr-2">
                  {isLoading && historyItems.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-primary font-mono animate-pulse">Loading archive interface...</div>
                  ) : filteredHistory.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-outline font-mono">No matching items found.</div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 pb-4">
                      {filteredHistory.map((item) => (
                        <div 
                          key={item.id}
                          onClick={() => navigate(item.status === 'ACTIVE' ? `/repair/${item.id}` : `/iteration/${item.id}`)}
                          className={cn(
                            "bg-surface-container-low border p-5 flex flex-col cursor-pointer group hover:-translate-y-1 transition-all relative overflow-hidden",
                            item.status === 'ACTIVE' ? "border-primary shadow-[0_0_15px_rgba(99,102,241,0.1)]" : "border-outline-variant/30 hover:border-primary/50"
                          )}
                        >
                          {/* Glowing Accent */}
                          <div className={cn(
                            "absolute top-0 right-0 w-24 h-24 -mr-12 -mt-12 bg-gradient-to-br transition-opacity opacity-0 group-hover:opacity-10",
                            item.status === 'COMMITTED' ? "from-secondary to-transparent" : (item.status === 'ACTIVE' ? "from-primary to-transparent" : "from-error to-transparent")
                          )}></div>

                          <div className="flex justify-between items-start mb-4 font-mono text-[10px] font-black">
                            <span className={cn(
                              "px-2 py-0.5 rounded-sm flex items-center gap-1",
                              item.status === 'COMMITTED' ? "bg-secondary/10 text-secondary" : (item.status === 'ACTIVE' ? "bg-primary text-on-primary" : "bg-error/10 text-error")
                            )}>
                              {item.status === 'ACTIVE' && <div className="w-1.5 h-1.5 rounded-full bg-current animate-pulse mr-1"></div>}
                              {item.status}
                            </span>
                            <span className="text-outline/60">{item.fullDate} {item.date}</span>
                          </div>

                          <div className="flex-1 space-y-3">
                            <div>
                              <h3 className="text-sm font-black text-on-surface group-hover:text-primary transition-colors font-sans">{item.title}</h3>
                              <div className="text-[10px] text-outline font-semibold mt-1 font-sans truncate">{item.userPrompt || item.category}</div>
                            </div>
                            <div className="font-sans text-[11px] font-bold text-on-surface-variant flex items-center gap-2">
                              <Zap className="w-3 h-3 text-secondary" />
                              {item.codeSnippet}
                            </div>
                          </div>

                          <div className="mt-4 pt-3 border-t border-outline-variant/30 flex justify-between items-center opacity-50 group-hover:opacity-100 transition-all font-sans">
                            <span className="text-xs font-semibold text-primary">Inspect</span>
                            <ChevronRight className="w-4 h-4 text-primary" />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Pagination Footer */}
                <div className="h-14 shrink-0 bg-surface-container-high border-t border-outline-variant/30 px-6 flex justify-between items-center">
                    <span className="font-mono text-[10px] text-outline uppercase tracking-widest">Showing {filteredHistory.length} items</span>
                    <div className="flex items-center gap-4">
                        <button 
                            onClick={() => setPage(p => Math.max(0, p - 1))}
                            disabled={page === 0 || isLoading}
                            className="px-3 py-1 bg-surface-container-low hover:bg-primary/20 text-outline hover:text-primary disabled:opacity-30 border border-outline-variant/30 rounded text-xs font-mono font-bold transition-colors uppercase"
                        >
                            Prev
                        </button>
                        <span className="text-sm font-mono font-black text-primary">Page {page + 1}</span>
                        <button 
                            onClick={() => setPage(p => p + 1)}
                            disabled={historyItems.length < limit || isLoading}
                            className="px-3 py-1 bg-surface-container-low hover:bg-primary/20 text-outline hover:text-primary disabled:opacity-30 border border-outline-variant/30 rounded text-xs font-mono font-bold transition-colors uppercase"
                        >
                            Next
                        </button>
                    </div>
                </div>
            </div>
        </div>
      </div>
    </div>
  );
};
