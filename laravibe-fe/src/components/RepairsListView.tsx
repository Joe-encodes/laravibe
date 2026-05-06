import React from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { Activity, Server, Zap, ArrowRight, Search } from 'lucide-react';
import { cn } from '../lib/utils';

export const RepairsListView: React.FC = () => {
  const navigate = useNavigate();
  const [activeRepairs, setActiveRepairs] = React.useState<any[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [searchQuery, setSearchQuery] = React.useState('');

  const fetchRepairs = async () => {
    setIsLoading(true);
    try {
      const sessionToken = localStorage.getItem('laravibe_session_token');
      // Fetching from history but filtering for active/running tasks (mocking logic)
      const res = await fetch(`/api/history?skip=0&limit=50`, { 
        headers: { 'Authorization': `Bearer ${sessionToken}` } 
      });
      if (!res.ok) throw new Error('API Error');
      const data = await res.json();
      
      const mapped = data.map((sub: any) => ({
        id: sub.id,
        title: `Repair Node #${sub.id.substring(0, 8)}`,
        iterations: sub.total_iterations,
        status: sub.status === 'success' ? 'COMMITTED' : (sub.status === 'running' ? 'ACTIVE' : 'FAILED'),
        date: new Date(sub.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        category: sub.category || 'SYSTEM_REPAIR',
      }));
      // In a real scenario, this would filter by 'running' or 'pending'
      setActiveRepairs(mapped);
    } catch (err) {
      console.error('Failed to load active repairs:', err);
    } finally {
      setIsLoading(false);
    }
  };

  React.useEffect(() => {
    fetchRepairs();
    // Poll every 5s for active dashboard
    const interval = setInterval(fetchRepairs, 5000);
    return () => clearInterval(interval);
  }, []);

  const filteredRepairs = activeRepairs.filter(item => 
    item.id.toLowerCase().includes(searchQuery.toLowerCase()) || 
    item.status.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex-1 bg-surface-container-lowest p-4 md:p-8 overflow-hidden flex flex-col relative">
      <div className="max-w-6xl mx-auto w-full flex-1 flex flex-col h-full relative z-10">
        
        {/* Header Block */}
        <div className="mb-8 md:mb-10 border-b border-outline-variant pb-6 flex flex-col md:flex-row md:items-end justify-between gap-4">
          <div className="space-y-3">
             <div className="flex items-center gap-2">
               <Server className="w-4 h-4 text-primary" />
               <span className="font-mono text-[10px] font-black text-primary uppercase tracking-[0.4em]">Operations_Center</span>
             </div>
            <h1 className="font-mono text-3xl md:text-4xl font-black tracking-tighter text-on-surface uppercase italic flex items-center gap-4">
              Active_Nodes
              <div className="h-2 w-2 rounded-full bg-primary animate-ping"></div>
            </h1>
            <p className="text-on-surface-variant font-mono max-w-2xl text-sm leading-relaxed opacity-70">
              Real-time telemetry and management of ongoing repair synthesis across the Laravibe cluster.
            </p>
          </div>
          <div className="flex items-center gap-4 bg-surface-container-high border border-outline-variant/30 px-4 py-2 rounded-sm backdrop-blur-md w-full md:w-auto">
            <Search className="w-4 h-4 text-outline" />
            <input 
              type="text" 
              placeholder="Filter nodes..." 
              className="bg-transparent outline-none text-sm text-on-surface w-full md:w-36 font-mono"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        {/* Telemetry Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8 shrink-0">
          {[
            { label: 'Active_Containers', val: activeRepairs.filter(r => r.status === 'ACTIVE').length.toString(), icon: Activity, color: 'text-primary' },
            { label: 'System_Load', val: '42%', icon: Server, color: 'text-secondary' },
            { label: 'Total_Processed', val: activeRepairs.length.toString(), icon: Zap, color: 'text-outline' },
          ].map((stat, i) => (
            <div key={i} className="bg-surface-container-low border border-outline-variant/30 p-4 flex flex-col gap-2">
               <div className="flex items-center gap-2 opacity-50">
                 <stat.icon className="w-3 h-3" />
                 <span className="font-mono text-[9px] font-black uppercase tracking-tighter">{stat.label}</span>
               </div>
               <div className={cn("text-2xl font-mono font-black italic", stat.color)}>{stat.val}</div>
            </div>
          ))}
        </div>

        {/* Active Nodes Grid */}
        <div className="flex-1 overflow-y-auto custom-scrollbar pr-2">
          {isLoading && activeRepairs.length === 0 ? (
            <div className="flex items-center justify-center h-full text-primary font-mono animate-pulse">Scanning cluster...</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 pb-12">
              <AnimatePresence>
                {filteredRepairs.map((item) => (
                  <motion.div 
                    key={item.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
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
                      <span className="text-outline/60">{item.date}</span>
                    </div>

                    <div className="flex-1 space-y-3">
                      <div>
                        <h3 className="text-sm font-black text-on-surface group-hover:text-primary transition-colors font-mono">{item.title}</h3>
                        <div className="text-[10px] text-outline font-semibold mt-1 font-mono">{item.category}</div>
                      </div>
                      <div className="font-mono text-[11px] font-bold text-on-surface-variant flex items-center gap-2">
                        <Zap className="w-3 h-3 text-secondary" />
                        {item.iterations} cycles executed
                      </div>
                    </div>

                    <div className="mt-4 pt-3 border-t border-outline-variant/30 flex justify-between items-center opacity-50 group-hover:opacity-100 transition-all font-mono">
                      <span className="text-xs font-semibold text-primary">View stream</span>
                      <ArrowRight className="w-4 h-4 text-primary" />
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
