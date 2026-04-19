import React from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { Activity, Shield, Cpu, Zap, Search, History, ChevronDown, ArrowRight } from 'lucide-react';
import { cn } from '../lib/utils';
import { MASTER_REPAIR_TOKEN } from '../constants';

export const HistoryView: React.FC = () => {
  const navigate = useNavigate();
  const [isDrawerOpen, setIsDrawerOpen] = React.useState(true);
  const [historyItems, setHistoryItems] = React.useState<any[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [searchQuery, setSearchQuery] = React.useState('');

  React.useEffect(() => {
    const fetchHistory = async () => {
      console.info('[LaraVibe] Fetching repair history...');
      try {
        const response = await fetch('/api/history?limit=20', {
          headers: {
            'Authorization': `Bearer ${MASTER_REPAIR_TOKEN}`
          }
        });
        console.info('[LaraVibe] History API Response:', { status: response.status });
        if (!response.ok) throw new Error('API Error');
        const data = await response.json();
        console.info('[LaraVibe] History entries loaded:', data.length);
        
        const mapped = data.map((sub: any) => ({
          id: sub.id,
          title: `# NODE_${sub.id.substring(0, 8)}`,
          codeSnippet: sub.total_iterations + " Iterations",
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
    fetchHistory();
  }, []);

  const filteredHistory = historyItems.filter(item => 
    item.id.toLowerCase().includes(searchQuery.toLowerCase()) || 
    item.status.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex-1 bg-surface-container-lowest p-8 overflow-hidden flex flex-col relative">
      <div className="max-w-6xl mx-auto w-full flex-1 flex flex-col">
        {/* Superior Header */}
        <div className="mb-12 flex justify-between items-end border-b border-outline-variant pb-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="w-1 h-4 bg-primary"></div>
              <span className="mono text-[10px] font-black text-primary uppercase tracking-[0.4em]">Operational_Archives</span>
            </div>
            <h1 className="font-mono text-5xl font-black tracking-tighter text-on-surface uppercase italic">Repair_Hub_v1</h1>
            <p className="text-on-surface-variant font-sans max-w-xl text-sm leading-relaxed opacity-70">
              Access the immutable ledger of synthesized patches and diagnostic sequences. Every iteration is cryptographically logged for audit compliance.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
             <div className="flex items-center gap-4 bg-surface-container-high border border-outline-variant/30 px-4 py-2 rounded-sm backdrop-blur-md">
                <Search className="w-4 h-4 text-outline" />
                <input 
                  type="text" 
                  placeholder="Filter Archives..." 
                  className="bg-transparent outline-none mono text-[10px] font-bold text-on-surface w-32 uppercase"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
             </div>
          </div>
        </div>

        {/* Bento Grid Stats */}
        <div className="grid grid-cols-12 gap-6 mb-12">
          <div className="col-span-4 bg-surface-container-low border border-outline-variant/50 p-6 relative group overflow-hidden">
            <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
              <Zap className="w-24 h-24 text-primary" />
            </div>
            <h2 className="font-mono text-[10px] font-black text-outline uppercase tracking-widest mb-4">Neural_Efficiency</h2>
            <div className="flex items-baseline gap-2">
              <span className="text-4xl font-mono font-black text-on-surface italic">
                {historyItems.length > 0 ? (historyItems.filter(i => i.status === 'COMMITTED').length / historyItems.length * 100).toFixed(1) : '0.0'}
                <span className="text-primary text-xl">%</span>
              </span>
              <span className="text-[10px] text-secondary font-bold">ARC_LOADED</span>
            </div>
            <div className="mt-4 flex gap-1">
              {[...Array(12)].map((_, i) => (
                <div key={i} className={cn("h-4 w-1 rounded-full", i < (historyItems.length % 12) ? "bg-primary" : "bg-surface-container-highest")}></div>
              ))}
            </div>
          </div>

          <div className="col-span-8 bg-surface-container-low border border-outline-variant/50 p-6 relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-r from-primary/5 to-transparent"></div>
            <h2 className="font-mono text-[10px] font-black text-outline uppercase tracking-widest mb-4">System_Telemetry</h2>
            <div className="grid grid-cols-3 gap-8 relative z-10">
              {[
                { label: 'Archive_Count', val: historyItems.length.toString(), icon: Activity },
                { label: 'Integrity_Index', val: historyItems.length > 5 ? 'A+' : '---', icon: Shield },
                { label: 'Kernel_Bus', val: '1.2ms', icon: Cpu }
              ].map((stat, i) => (
                <div key={i} className="space-y-1">
                   <div className="flex items-center gap-2 text-outline">
                     <stat.icon className="w-3 h-3" />
                     <span className="mono text-[9px] uppercase font-bold">{stat.label}</span>
                   </div>
                   <div className="text-2xl font-mono font-black">{stat.val}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Empty State / Main Content Placeholder */}
        {!isLoading && filteredHistory.length === 0 && (
          <div className="flex-1 flex flex-col items-center justify-center opacity-30 gap-4">
             <History className="w-16 h-16" />
             <span className="mono text-xs font-bold uppercase tracking-[0.3em]">No_Matching_Sequence_Found</span>
          </div>
        )}
      </div>

      {/* History Drawer: The "File Explorer" Style */}
      <section className={cn(
        "fixed bottom-12 left-16 right-0 bg-machined-header/80 backdrop-blur-xl border-t border-outline-variant/30 z-40 transition-all duration-500 flex flex-col shadow-[0_-20px_50px_rgba(0,0,0,0.3)]",
        isDrawerOpen ? "h-[320px]" : "h-12"
      )}>
        <div className="px-8 h-12 border-b border-outline-variant/30 flex items-center justify-between shrink-0 cursor-pointer hover:bg-white/5 transition-colors" onClick={() => setIsDrawerOpen(!isDrawerOpen)}>
          <div className="flex items-center gap-3">
            <History className={cn("w-4 h-4 text-primary transition-transform duration-500", isDrawerOpen && "rotate-[360deg]")} />
            <span className="font-mono text-[11px] uppercase font-black text-on-surface tracking-[0.2em]">Sequence_Vault_Explorer</span>
            <div className="w-1 h-3 bg-primary animate-pulse ml-2"></div>
          </div>
          <div className="flex items-center gap-6">
            <span className="font-mono text-[10px] text-outline font-bold uppercase">Load: {filteredHistory.length} ENTRIES</span>
            <ChevronDown className={cn("w-5 h-5 text-outline transition-transform duration-500", !isDrawerOpen && "rotate-180")} />
          </div>
        </div>

        <div className={cn(
          "flex-1 overflow-x-auto overflow-y-hidden custom-scrollbar flex items-center gap-6 px-10 transition-all duration-500 py-4",
          isDrawerOpen ? "opacity-100 translate-y-0" : "opacity-0 translate-y-10 pointer-events-none"
        )}>
          <AnimatePresence>
            {isLoading ? (
              <div className="mono text-xs font-bold text-primary animate-pulse">BOOTING_ARCHIVE_INTERFACE...</div>
            ) : (
              filteredHistory.map((item, i) => (
                <motion.article 
                  key={item.id}
                  initial={{ opacity: 0, scale: 0.9, x: 20 }}
                  animate={{ opacity: 1, scale: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  onClick={() => navigate(`/iteration/${item.id}`)}
                  className={cn(
                    "w-[260px] h-full bg-surface-container-low border p-6 flex flex-col shrink-0 transition-all cursor-pointer group hover:-translate-y-2 relative overflow-hidden",
                    item.status === 'ACTIVE' ? "border-primary shadow-[0_0_30px_rgba(192,193,255,0.15)]" : "border-outline-variant/20 hover:border-primary/50 hover:bg-surface-container-high"
                  )}
                >
                  {/* Glowing Accent */}
                  <div className={cn(
                    "absolute top-0 right-0 w-24 h-24 -mr-12 -mt-12 bg-gradient-to-br transition-opacity opacity-0 group-hover:opacity-10",
                    item.status === 'COMMITTED' ? "from-secondary to-transparent" : "from-error to-transparent"
                  )}></div>

                  <div className="flex justify-between items-start mb-6 font-mono text-[10px] font-black">
                    <span className={cn(
                      "px-2 py-0.5 rounded-sm",
                      item.status === 'COMMITTED' ? "bg-secondary/10 text-secondary" : (item.status === 'ACTIVE' ? "bg-primary text-on-primary" : "bg-error/10 text-error")
                    )}>
                      {item.status}
                    </span>
                    <span className="text-outline/60">{item.date}</span>
                  </div>

                  <div className="flex-1 space-y-4">
                    <div>
                      <h3 className="mono text-sm font-black text-on-surface group-hover:text-primary transition-colors italic">{item.title}</h3>
                      <div className="mono text-[9px] text-outline font-bold mt-1 uppercase tracking-tighter opacity-50">{item.fullDate}</div>
                    </div>
                    
                    <div className="space-y-1.5 opacity-70 group-hover:opacity-100 transition-opacity">
                      <div className="mono text-[11px] font-bold text-on-surface-variant flex items-center gap-2">
                        <Zap className="w-3 h-3 text-secondary" />
                        {item.codeSnippet}
                      </div>
                      <div className="mono text-[9px] text-outline uppercase tracking-widest font-black italic truncate">Type: {item.category}</div>
                      {item.userPrompt && (
                        <div className="mono text-[9px] text-primary/70 uppercase tracking-widest font-bold truncate mt-1">
                          Prompt: "{item.userPrompt}"
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="mt-4 pt-4 border-t border-outline-variant/30 flex justify-between items-center opacity-0 group-hover:opacity-100 transition-all translate-y-2 group-hover:translate-y-0">
                    <span className="mono text-[9px] font-black text-primary uppercase">Inspect_Node</span>
                    <ArrowRight className="w-4 h-4 text-primary" />
                  </div>
                </motion.article>
              ))
            )}
          </AnimatePresence>
          {/* Spacer for horizontal scroll */}
          <div className="w-10 shrink-0 h-1"></div>
        </div>
      </section>
    </div>
  );
};
