import React from 'react';
import { FileCode, ShieldCheck, Zap, Download, Layers } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { Patch } from '../types';

interface CodeSynthesisPanelProps {
  code: string;
  patches: Patch[];
  isComplete: boolean;
  onDownload?: () => void;
}

export const CodeSynthesisPanel: React.FC<CodeSynthesisPanelProps> = ({ 
  code, 
  patches, 
  isComplete,
  onDownload 
}) => {
  const lines = code.split('\n');
  
  return (
    <section className="w-1/3 flex flex-col bg-surface-container-low border-l border-outline-variant overflow-hidden">
      <div className="h-12 px-4 flex items-center justify-between border-b border-outline-variant bg-surface-container-high/50 shrink-0">
        <div className="flex items-center gap-2">
          <Layers className="w-3 h-3 text-secondary" />
          <h2 className="mono text-[10px] font-bold tracking-[0.2em] text-on-surface-variant uppercase">Synthesis_Vault</h2>
        </div>
        <div className="flex items-center gap-2">
          {isComplete && (
            <motion.div 
              initial={{ scale: 0 }} 
              animate={{ scale: 1 }}
              className="flex items-center gap-1 bg-secondary/20 px-2 py-0.5 rounded border border-secondary/30"
            >
              <ShieldCheck className="w-2.5 h-2.5 text-secondary" />
              <span className="mono text-[8px] font-black text-secondary uppercase">Verified</span>
            </motion.div>
          )}
          <div className="w-2 h-2 rounded-full bg-outline-variant animate-pulse"></div>
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-surface-container-lowest p-0 custom-scrollbar relative">
        {!code ? (
          <div className="h-full flex flex-col items-center justify-center text-center opacity-30 px-6">
            <Zap className="w-8 h-8 mb-4 stroke-[1px] text-primary" />
            <p className="mono text-[9px] uppercase tracking-tighter">Awaiting Logic Synthesis...</p>
          </div>
        ) : (
          <div className="flex min-w-full font-mono text-[11px] leading-relaxed py-4">
            {/* Line Numbers */}
            <div className="w-10 shrink-0 text-right pr-3 border-r border-outline-variant/10 text-outline/30 select-none">
              {lines.map((_, i) => (
                <div key={i} className="h-5">{i + 1}</div>
              ))}
            </div>
            
            {/* Code Content */}
            <pre className="flex-1 pl-4 text-on-surface-variant whitespace-pre">
              {lines.map((line, i) => {
                // Check if this line was recently patched (simplified logic)
                const isPatched = patches.some(p => p.content.includes(line) && line.trim().length > 5);
                return (
                  <div 
                    key={i} 
                    className={cn(
                      "h-5 px-1 transition-colors duration-1000",
                      isPatched ? "bg-secondary/10 text-secondary" : "hover:bg-primary/5"
                    )}
                  >
                    {line || ' '}
                  </div>
                );
              })}
            </pre>
          </div>
        )}

        {/* Floating Patches Overlay */}
        <div className="absolute top-4 right-4 flex flex-col gap-2 items-end">
          <AnimatePresence>
            {patches.slice(-3).map((patch, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: 20, scale: 0.9 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0, x: 20, scale: 0.9 }}
                className="bg-surface-container-high/90 backdrop-blur-md border border-primary/30 p-2 rounded shadow-xl max-w-[200px]"
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <div className="w-1 h-3 bg-primary"></div>
                  <span className="mono text-[8px] font-black text-primary truncate uppercase">{patch.path}</span>
                </div>
                <div className="text-[8px] text-on-surface-variant mono truncate opacity-60">
                  ACTION: {patch.action}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>

      {isComplete && (
        <motion.div 
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className="p-4 bg-surface-container-high/50 border-t border-outline-variant shrink-0 flex gap-2"
        >
          <button 
            onClick={onDownload}
            className="flex-1 flex items-center justify-center gap-2 bg-primary text-on-primary py-2 rounded mono text-[10px] font-bold uppercase tracking-widest hover:brightness-110 active:scale-95 transition-all shadow-lg shadow-primary/20"
          >
            <Download className="w-3 h-3" />
            Direct_Export
          </button>
          <button 
            className="px-3 flex items-center justify-center bg-surface-container-highest border border-outline-variant rounded hover:border-secondary/40 transition-colors"
            title="Apply to Sandbox"
          >
            <Zap className="w-3 h-3 text-secondary" />
          </button>
        </motion.div>
      )}

      <div className="h-8 px-4 flex items-center justify-between bg-surface-container-low border-t border-outline-variant shrink-0">
        <span className="mono text-[8px] text-outline font-bold uppercase tracking-widest">Syntax: PHP_LARAVEL</span>
        <div className="flex items-center gap-1">
          <div className="w-1.5 h-1.5 rounded-full bg-secondary"></div>
          <span className="mono text-[8px] text-secondary font-bold uppercase">Kernel_Linked</span>
        </div>
      </div>
    </section>
  );
};
