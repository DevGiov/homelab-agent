import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Brain, Cpu, Palette, Settings as SettingsIcon, Shield, X, type LucideIcon } from 'lucide-react';
import { getMemories } from '../../api/memory';
import { AppearanceTab } from './AppearanceTab';
import { GeneralTab } from './GeneralTab';
import { MemoryTab } from './MemoryTab';
import { SecurityTab } from './SecurityTab';

type SettingsTab = 'general' | 'appearance' | 'memory' | 'security';

/** Modale delle impostazioni; ogni scheda carica i propri dati quando viene aperta. */
export const SettingsModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  const [memoryTotal, setMemoryTotal] = useState<number | null>(null);

  // Il numero di fatti compare nell'etichetta della scheda anche prima di aprirla
  useEffect(() => {
    getMemories('fact', 1)
      .then((res) => setMemoryTotal(res.total))
      .catch((err) => console.warn('Errore conteggio memorie:', err));
  }, []);

  const tabs: Array<{ id: SettingsTab; label: string; icon: LucideIcon; iconColor?: string }> = [
    { id: 'general', label: 'Generale', icon: Cpu },
    { id: 'appearance', label: 'Aspetto & Temi', icon: Palette },
    { id: 'memory', label: `Memoria (${memoryTotal ?? '…'})`, icon: Brain, iconColor: 'text-purple-400' },
    { id: 'security', label: 'Sicurezza', icon: Shield, iconColor: 'text-amber-400' },
  ];

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div onClick={onClose} className="absolute inset-0 bg-bg/80 backdrop-blur-md transition-opacity" />

      <div className="relative glass-panel border border-border rounded-2xl shadow-2xl w-full max-w-xl p-5 space-y-4 text-fg max-h-[90vh] flex flex-col z-10">
        <div className="flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 text-fg">
            <SettingsIcon size={16} className="text-accent" />
            <span className="font-semibold text-sm">Impostazioni & Personalizzazione</span>
          </div>
          <button onClick={onClose} className="p-1 text-fg-muted hover:text-fg hover:bg-panel rounded-lg transition cursor-pointer">
            <X size={16} />
          </button>
        </div>

        <div className="flex gap-1 bg-panel/80 rounded-xl p-1 border border-border shrink-0">
          {tabs.map(({ id, label, icon: Icon, iconColor }) => {
            const isActive = activeTab === id;
            return (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
                  isActive ? 'bg-accent text-white shadow-sm shadow-accent/25' : 'text-fg-muted hover:text-fg'
                }`}
              >
                <Icon size={13} className={isActive ? 'text-white' : iconColor} />
                {label}
              </button>
            );
          })}
        </div>

        <div className="flex-1 overflow-y-auto space-y-4 pr-1 custom-scrollbar">
          {activeTab === 'general' && <GeneralTab onSaved={onClose} />}
          {activeTab === 'appearance' && <AppearanceTab />}
          {activeTab === 'memory' && <MemoryTab onTotalChange={setMemoryTotal} />}
          {activeTab === 'security' && <SecurityTab />}
        </div>
      </div>
    </div>,
    document.body
  );
};
