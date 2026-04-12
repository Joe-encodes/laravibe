import React from 'react';
import { Database, ShieldAlert, Cpu, Layers, Layout, ChevronRight, Activity, Terminal } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';

export const AdminDashboardView: React.FC = () => {
  const [datasets, setDatasets] = React.useState<any[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);

  React.useEffect(() => {
    const fetchDatasets = async () => {
      console.info('[LaraVibe] Fetching training datasets...');
      try {
        const response = await fetch('/api/admin/training-dataset', {
          headers: { 'Authorization': 'Bearer DUMMY_ADMIN_TOKEN' } // Replace with Supabase token later
        });
        console.info('[LaraVibe] Admin API Response:', { status: response.status });
        if (!response.ok) throw new Error('API Error');
        const payload = await response.json();
        console.info('[LaraVibe] Datasets loaded:', payload.total);
        setDatasets(payload.data);
      } catch (err) {
        console.error('Failed to load datasets:', err);
      } finally {
        setIsLoading(false);
      }
    };
    fetchDatasets();
  }, []);

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
              Training_Data_Vault
              <div className="h-2 w-2 bg-secondary rounded-full animate-pulse shadow-[0_0_10px_rgba(78,222,163,0.5)]"></div>
            </h1>
            <p className="text-on-surface-variant font-sans max-w-2xl text-sm leading-relaxed opacity-70">
              Curated repository of anonymized repair synthesis. These pairs represent the gold standard for model fine-tuning and knowledge distillation processes.
            </p>
          </div>
          <div className="flex gap-4">
             <div className="bg-surface-container-high px-6 py-3 border-2 border-primary/20 flex flex-col items-end gap-1">
                <span className="mono text-[9px] font-black text-outline uppercase tracking-widest">Dataset_Sync</span>
                <div className="flex items-center gap-3">
                   <Database className="w-5 h-5 text-secondary" />
                   <span className="text-2xl font-mono font-black text-on-surface">{datasets.length}</span>
                </div>
             </div>
          </div>
        </div>

        {/* Hero Stats HUD */}
        <div className="grid grid-cols-4 gap-4 mb-8">
           {[
             { label: 'Dataset_Entries', val: datasets.length.toString(), icon: Database, color: 'text-secondary' },
             { label: 'Vault_Integrity', val: datasets.length > 10 ? 'A+' : '---', icon: ShieldAlert, color: 'text-primary' },
             { label: 'Archive_Load', val: datasets.length > 0 ? (datasets.reduce((acc, curr) => acc + curr.iterations, 0) / datasets.length).toFixed(1) : '0', icon: Activity, color: 'text-primary' },
             { label: 'Kernel_Uptime', val: '∞', icon: Terminal, color: 'text-secondary' }
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

        {/* Dataset Grid */}
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
      </div>
    </div>
  );
};
