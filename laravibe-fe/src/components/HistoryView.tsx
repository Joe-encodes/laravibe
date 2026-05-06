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
    <div className="flex-1 bg-surface-container-lowest p-4 md:p-8 overflow-hidden flex flex-col relative">
      <div className="absolute top-0 right-0 w-1/2 h-full bg-gradient-to-l from-primary/5 to-transparent pointer-events-none"></div>
      
      <div className="max-w-6xl mx-auto h-full flex flex-col relative z-10 w-full">
        {/* Header Block */}
        <div className="mb-8 md:mb-10 border-b border-outline-variant pb-6 flex flex-col md:flex-row md:items-end justify-between gap-4">
          <div className="space-y-3">
             <div className="flex items-center gap-2">
               <History className="w-4 h-4 text-primary" />
               <span className="font-mono text-[10px] font-black text-primary uppercase tracking-[0.4em]">Operational_Archives</span>
             </div>
            <h1 className="font-mono text-3xl md:text-4xl font-black tracking-tighter text-on-surface uppercase italic flex items-center gap-4">
              Repair_Hub
            </h1>
            <p className="text-on-surface-variant font-mono max-w-2xl text-sm leading-relaxed opacity-70">
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
            
            <div className="flex-1 flex flex-col bg-surface-container-low/30 border border-outline-variant/20 rounded-md overflow-hidden">
                <div className="flex-1 overflow-y-auto custom-scrollbar">
                    <table className="w-full text-left border-collapse min-w-[600px]">
                        <thead className="sticky top-0 bg-surface-container-high z-10">
                            <tr className="border-b border-outline-variant">
                                <th className="p-4 font-mono text-[10px] text-outline uppercase font-black">Repair_ID</th>
                                <th className="p-4 font-mono text-[10px] text-outline uppercase font-black">Status</th>
                                <th className="p-4 font-mono text-[10px] text-outline uppercase font-black">Iterations</th>
                                <th className="p-4 font-mono text-[10px] text-outline uppercase font-black">Prompt_Snippet</th>
                                <th className="p-4 font-mono text-[10px] text-outline uppercase font-black">Date</th>
                                <th className="p-4 font-mono text-[10px] text-outline uppercase font-black">Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {isLoading && historyItems.length === 0 ? (
                                <tr>
                                    <td colSpan={6} className="p-8 text-center text-primary font-mono text-sm animate-pulse">Loading archive interface...</td>
                                </tr>
                            ) : filteredHistory.length === 0 ? (
                                <tr>
                                    <td colSpan={6} className="p-8 text-center text-outline font-mono text-sm">No matching items found.</td>
                                </tr>
                            ) : (
                                filteredHistory.map((item) => (
                                <tr key={item.id} className="border-b border-outline-variant/30 hover:bg-primary/5 transition-colors group">
                                    <td className="p-4 font-mono text-xs text-on-surface">{item.id}</td>
                                    <td className="p-4 font-mono text-[10px] font-black">
                                        <span className={cn(
                                            "px-2 py-0.5 rounded-sm",
                                            item.status === 'COMMITTED' ? "bg-secondary/10 text-secondary" : (item.status === 'ACTIVE' ? "bg-primary text-on-primary" : "bg-error/10 text-error")
                                        )}>
                                            {item.status}
                                        </span>
                                    </td>
                                    <td className="p-4 font-mono text-xs text-on-surface-variant flex items-center gap-1"><Zap className="w-3 h-3 text-secondary"/>{item.codeSnippet}</td>
                                    <td className="p-4 font-mono text-[10px] text-outline max-w-[200px] truncate">{item.userPrompt || item.category}</td>
                                    <td className="p-4 font-mono text-[10px] text-outline">{item.fullDate} {item.date}</td>
                                    <td className="p-4">
                                        <button 
                                            onClick={() => navigate(item.status === 'ACTIVE' ? `/repair/${item.id}` : `/iteration/${item.id}`)}
                                            className="text-primary font-mono text-[11px] font-black uppercase tracking-widest hover:underline group-hover:translate-x-1 transition-transform inline-flex items-center gap-2"
                                        >
                                            Inspect <ChevronRight className="w-3 h-3" />
                                        </button>
                                    </td>
                                </tr>
                                ))
                            )}
                        </tbody>
                    </table>
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
