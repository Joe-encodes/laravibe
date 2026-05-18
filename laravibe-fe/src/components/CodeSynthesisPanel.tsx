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
    <section className="w-1/3 flex flex-col border-l border-machined-border machined-panel z-10 shadow-[-10px_0_20px_rgba(0,0,0,0.2)]">
      <div className="h-12 px-4 flex items-center justify-between border-b border-machined-border bg-surface-container-high/80 backdrop-blur-md shrink-0">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-secondary" />
          <h2 className="text-hud text-on-surface-variant">SYNTHESIS_VAULT</h2>
        </div>
        <div className="flex items-center gap-3">
          {isComplete && (
            <motion.div 
              initial={{ scale: 0 }} 
              animate={{ scale: 1 }}
              className="flex items-center gap-1.5 bg-secondary/10 px-2.5 py-1 rounded-sm border border-secondary/30 primary-glow"
            >
              <ShieldCheck className="w-3 h-3 text-secondary" />
              <span className="text-hud text-secondary">VERIFIED</span>
            </motion.div>
          )}
          <div className="w-2 h-2 rounded-sm bg-outline-variant/50 animate-pulse"></div>
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-surface-container-lowest/80 p-0 custom-scrollbar relative scanlines">
        {!code ? (
          <div className="h-full flex flex-col items-center justify-center text-center opacity-30 px-6">
            <Zap className="w-12 h-12 mb-4 stroke-[1px] text-primary" />
            <p className="text-hud text-on-surface-variant">AWAITING_LOGIC_SYNTHESIS...</p>
          </div>
        ) : (
          <div className="flex min-w-full text-log py-4 relative z-10">
            {/* Line Numbers */}
            <div className="w-10 shrink-0 text-right pr-3 border-r border-outline-variant/20 text-outline/40 select-none bg-surface-container-lowest/50 backdrop-blur-sm sticky left-0">
              {lines.map((_, i) => (
                <div key={i} className="h-5">{i + 1}</div>
              ))}
            </div>
            
            {/* Code Content */}
            <pre className="flex-1 pl-4 text-on-surface-variant whitespace-pre">
              {lines.map((line, i) => {
                const isPatched = patches.some(p => p.content.includes(line) && line.trim().length > 5);
                // Very basic pseudo-syntax highlighting for visual flair
                const isComment = line.trim().startsWith('//');
                const isKeyword = line.match(/\b(public|private|protected|function|class|return|if|else)\b/);
                
                return (
                  <div 
                    key={i} 
                    className={cn(
                      "h-5 px-1 transition-colors duration-1000",
                      isPatched ? "bg-secondary/15 text-secondary primary-glow relative" : "hover:bg-primary/5",
                      isComment && !isPatched && "text-outline/60 italic",
                      isKeyword && !isPatched && !isComment && "text-primary/90 font-semibold"
                    )}
                  >
                    {isPatched && (
                      <span className="absolute left-0 top-0 bottom-0 w-[2px] bg-secondary shadow-[0_0_8px_rgba(78,222,163,1)]"></span>
                    )}
                    {line || ' '}
                  </div>
                );
              })}
            </pre>
          </div>
        )}

        {/* Floating Patches Overlay */}
        <div className="absolute top-4 right-4 flex flex-col gap-3 items-end z-20 pointer-events-none">
          <AnimatePresence>
            {patches.slice(-3).map((patch, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: 20, scale: 0.9 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0, x: 20, scale: 0.9 }}
                className="bg-surface-container-high/95 dark:bg-surface-container-high/90 backdrop-blur-xl p-3 rounded-lg border border-primary/20 dark:border-machined-border shadow-2xl max-w-[220px] pointer-events-auto"
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-secondary shadow-[0_0_8px_rgba(78,222,163,0.5)]"></div>
                  <span className="text-[10px] font-bold text-secondary uppercase tracking-wider truncate">{patch.action}</span>
                </div>
                <div className="text-[11px] text-on-surface font-mono break-all leading-tight font-semibold">
                  {patch.path}
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
          className="p-4 bg-surface-container-high/50 border-t border-machined-border shrink-0 flex gap-3 backdrop-blur-md relative z-10"
        >
          <button 
            onClick={onDownload}
            className="flex-1 flex items-center justify-center gap-2 bg-primary text-on-primary border border-primary py-2.5 rounded-md text-hud hover:brightness-110 active:scale-95 transition-all shadow-[0_0_15px_rgba(192,193,255,0.25)] group"
          >
            <Download className="w-4 h-4 group-hover:-translate-y-0.5 transition-transform" />
            DIRECT_EXPORT
          </button>
          <button 
            className="px-3 flex items-center justify-center gap-2 bg-surface-container-highest/50 border border-outline-variant/50 rounded-md hover:border-secondary hover:text-secondary hover:bg-secondary/10 transition-all group"
            title="Apply to Sandbox"
          >
            <Zap className="w-4 h-4 text-outline group-hover:text-secondary transition-colors" />
            <span className="text-[10px] font-bold text-outline group-hover:text-secondary whitespace-nowrap">APPLY_TO_SANDBOX</span>
          </button>
        </motion.div>
      )}

      <div className="h-6 px-4 flex items-center justify-between bg-machined-footer border-t border-machined-border shrink-0 relative z-10 opacity-30">
        <span className="text-[8px] font-bold tracking-widest text-outline">AUTO_PATCH_ACTIVE</span>
        <div className="w-1 h-1 rounded-full bg-secondary"></div>
      </div>
    </section>
  );
};
