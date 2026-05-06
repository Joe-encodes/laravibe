import React from 'react';
import { Box, Database, FileText, Layout, Share2, Globe } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { BoostContext } from '../types';

interface ContextDiscoveryPanelProps {
  contexts: BoostContext[];
}

const iconMap: Record<string, any> = {
  model: Database,
  migration: Box,
  controller: Layout,
  route: Share2,
  docs: FileText,
  default: Globe
};

export const ContextDiscoveryPanel: React.FC<ContextDiscoveryPanelProps> = ({ contexts }) => {
  return (
    <section className="w-80 flex flex-col border-r border-outline-variant bg-surface-container-low overflow-hidden">
      <div className="h-12 px-4 flex items-center justify-between border-b border-outline-variant bg-surface-container-high/50 shrink-0">
        <div className="flex items-center gap-2">
          <Database className="w-3 h-3 text-primary" />
          <h2 className="mono text-[10px] font-bold tracking-[0.2em] text-on-surface-variant uppercase">Discovery_Vault</h2>
        </div>
        <div className="flex gap-1">
          <div className="w-1 h-3 bg-primary/40"></div>
          <div className="w-1 h-3 bg-primary/20"></div>
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
        {contexts.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center opacity-30 px-6">
            <Share2 className="w-8 h-8 mb-4 stroke-[1px]" />
            <p className="mono text-[9px] uppercase tracking-tighter">Awaiting Context Injection...</p>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {contexts.map((ctx, idx) => {
              const Icon = iconMap[ctx.component_type.toLowerCase()] || iconMap.default;
              return (
                <motion.div
                  key={idx}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="bg-surface-container-lowest border border-outline-variant rounded p-3 relative overflow-hidden group hover:border-primary/40 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <Icon className="w-3 h-3 text-secondary" />
                    <span className="mono text-[10px] font-bold text-secondary uppercase tracking-widest">{ctx.component_type}</span>
                  </div>
                  <div className="mono text-[10px] text-on-surface-variant leading-relaxed line-clamp-6 opacity-80 font-medium">
                    {ctx.context_text}
                  </div>
                  {/* Glass Accent */}
                  <div className="absolute -bottom-2 -right-2 w-12 h-12 bg-secondary/5 rounded-full blur-xl group-hover:bg-secondary/10 transition-colors"></div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        )}
      </div>

      <div className="p-4 bg-surface-container-high/30 border-t border-outline-variant shrink-0">
        <div className="flex justify-between items-center mb-2">
          <span className="mono text-[9px] text-outline font-bold uppercase">Discovery_Depth</span>
          <span className="mono text-[9px] text-primary font-bold">{contexts.length} Units</span>
        </div>
        <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
          <motion.div 
            className="bg-primary h-full" 
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(contexts.length * 20, 100)}%` }}
          />
        </div>
      </div>
    </section>
  );
};
