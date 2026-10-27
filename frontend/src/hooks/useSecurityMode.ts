import { useSyncExternalStore } from 'react';
import type { SecurityMode } from '../api/chat';

const STORAGE_KEY = 'homelab_security_mode';
const listeners = new Set<() => void>();

const read = (): SecurityMode => (localStorage.getItem(STORAGE_KEY) as SecurityMode) || 'normal';

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export function setSecurityMode(mode: SecurityMode) {
  localStorage.setItem(STORAGE_KEY, mode);
  listeners.forEach((listener) => listener());
}

/** Modalità di sicurezza condivisa tra toolbar della chat e impostazioni, persistita in localStorage. */
export function useSecurityMode(): [SecurityMode, (mode: SecurityMode) => void] {
  return [useSyncExternalStore(subscribe, read), setSecurityMode];
}
