import React from 'react';
import { Keyboard, X } from 'lucide-react';

interface ShortcutsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ShortcutsModal: React.FC<ShortcutsModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div className="absolute inset-0 z-[60] flex items-center justify-center bg-surface-container-lowest/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl bg-surface-container-high border border-outline-variant shadow-2xl relative">
        {/* Modal Header */}
        <div className="flex justify-between items-center px-6 py-4 border-b border-outline-variant bg-surface-container-highest">
          <div className="flex items-center gap-3">
            <Keyboard className="w-5 h-5 text-primary" />
            <h1 className="mono text-lg font-bold tracking-tighter uppercase">LaraVibe Shortcuts</h1>
          </div>
          <button 
            onClick={onClose}
            className="text-outline hover:text-on-surface transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body: Machined Grid Layout */}
        <div className="p-8 grid grid-cols-2 gap-x-12 gap-y-6">
          {/* Shortcut Group: Navigation */}
          <div className="space-y-4">
            <h4 className="mono text-[10px] text-primary/60 font-bold uppercase tracking-[0.2em] mb-4">Core_Operations</h4>
            <div className="flex justify-between items-center group cursor-default">
              <span className="text-on-surface-variant font-medium text-sm">Run Diagnostics</span>
              <div className="flex gap-1">
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-primary rounded-sm min-w-[32px] text-center">Ctrl</kbd>
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-primary rounded-sm min-w-[32px] text-center">Enter</kbd>
              </div>
            </div>
            <div className="flex justify-between items-center group cursor-default">
              <span className="text-on-surface-variant font-medium text-sm">Upload Log Data</span>
              <div className="flex gap-1">
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-primary rounded-sm min-w-[32px] text-center">Ctrl</kbd>
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-primary rounded-sm min-w-[32px] text-center">O</kbd>
              </div>
            </div>
            <div className="flex justify-between items-center group cursor-default">
              <span className="text-on-surface-variant font-medium text-sm">Clear Terminal</span>
              <div className="flex gap-1">
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-primary rounded-sm min-w-[32px] text-center">Ctrl</kbd>
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-primary rounded-sm min-w-[32px] text-center">K</kbd>
              </div>
            </div>
          </div>

          {/* Shortcut Group: System */}
          <div className="space-y-4">
            <h4 className="mono text-[10px] text-secondary/60 font-bold uppercase tracking-[0.2em] mb-4">View_Controls</h4>
            <div className="flex justify-between items-center group cursor-default">
              <span className="text-on-surface-variant font-medium text-sm">Toggle Sidebar</span>
              <div className="flex gap-1">
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-secondary rounded-sm min-w-[32px] text-center">Ctrl</kbd>
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-secondary rounded-sm min-w-[32px] text-center">B</kbd>
              </div>
            </div>
            <div className="flex justify-between items-center group cursor-default">
              <span className="text-on-surface-variant font-medium text-sm">Search Files</span>
              <div className="flex gap-1">
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-secondary rounded-sm min-w-[32px] text-center">Ctrl</kbd>
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-secondary rounded-sm min-w-[32px] text-center">P</kbd>
              </div>
            </div>
            <div className="flex justify-between items-center group cursor-default">
              <span className="text-on-surface-variant font-medium text-sm">System Help</span>
              <div className="flex gap-1">
                <kbd className="mono bg-surface-container-lowest border border-outline-variant px-2 py-1 text-[11px] text-secondary rounded-sm min-w-[32px] text-center">?</kbd>
              </div>
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-4 bg-surface-container-lowest border-t border-outline-variant flex justify-between items-center">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-secondary animate-pulse rounded-full"></div>
            <span className="mono text-[9px] uppercase text-outline tracking-wider">Kernel Interface v2.4 Active</span>
          </div>
          <button 
            onClick={onClose}
            className="bg-primary text-on-primary-container px-4 py-1.5 mono text-[11px] font-bold uppercase rounded-sm hover:brightness-110 transition-all"
          >
            Dismiss_Interface
          </button>
        </div>

        {/* Decorative Corner Accents */}
        <div className="absolute -top-[1px] -left-[1px] w-4 h-4 border-t-2 border-l-2 border-primary"></div>
        <div className="absolute -bottom-[1px] -right-[1px] w-4 h-4 border-b-2 border-r-2 border-primary"></div>
      </div>
    </div>
  );
};
