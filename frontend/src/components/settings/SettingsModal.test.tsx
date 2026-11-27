import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

// Le schede caricano i propri dati: qui conta la barra delle schede, non il loro contenuto
vi.mock('./GeneralTab', () => ({ GeneralTab: () => <div>contenuto generale</div> }));
vi.mock('./providers/ProvidersTab', () => ({ ProvidersTab: () => <div>contenuto provider</div> }));
vi.mock('./AppearanceTab', () => ({ AppearanceTab: () => <div>contenuto aspetto</div> }));
vi.mock('./SecurityTab', () => ({ SecurityTab: () => <div>contenuto sicurezza</div> }));
vi.mock('./mcp/McpTab', () => ({ McpTab: () => <div>contenuto mcp</div> }));
vi.mock('./channels/ChannelsTab', () => ({ ChannelsTab: () => <div>contenuto canali</div> }));

import { SettingsModal } from './SettingsModal';

afterEach(cleanup);

const NAMES = ['Generale', 'Provider', 'Aspetto', 'Sicurezza', 'Server MCP', 'Canali'];

describe('schede delle impostazioni', () => {
  it('sono una tablist con nome; la scheda attiva è selezionata e collegata al pannello', () => {
    render(<SettingsModal onClose={() => {}} />);
    const list = screen.getByRole('tablist', { name: 'Sezioni delle impostazioni' });
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual(NAMES);
    expect(list.contains(tabs[0])).toBe(true);
    expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false', 'false', 'false', 'false']);
    expect(tabs.map((t) => t.tabIndex)).toEqual([0, -1, -1, -1, -1, -1]);

    const panel = screen.getByRole('tabpanel');
    expect(panel.getAttribute('aria-labelledby')).toBe(tabs[0].id);
    for (const t of tabs) expect(t.getAttribute('aria-controls')).toBe(panel.id);
    expect(new Set(tabs.map((t) => t.id)).size).toBe(tabs.length);
    expect(screen.getByText('contenuto generale')).toBeTruthy();
  });

  it('un clic cambia scheda e il pannello segue', () => {
    render(<SettingsModal onClose={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Sicurezza' }));
    expect(screen.getByRole('tab', { name: 'Sicurezza' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe(screen.getByRole('tab', { name: 'Sicurezza' }).id);
    expect(screen.getByText('contenuto sicurezza')).toBeTruthy();
    expect(screen.queryByText('contenuto generale')).toBeNull();
  });

  it('la scheda Canali mostra il suo contenuto', () => {
    render(<SettingsModal onClose={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Canali' }));
    expect(screen.getByText('contenuto canali')).toBeTruthy();
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe(screen.getByRole('tab', { name: 'Canali' }).id);
  });

  it('frecce, Home e Fine spostano focus e scheda, con ritorno al capo opposto', () => {
    render(<SettingsModal onClose={() => {}} />);
    const tab = (name: string) => screen.getByRole('tab', { name });
    const press = (key: string) => fireEvent.keyDown(document.activeElement as HTMLElement, { key });
    tab('Generale').focus();

    press('ArrowRight');
    expect(document.activeElement).toBe(tab('Provider'));
    expect(tab('Provider').getAttribute('aria-selected')).toBe('true');
    expect(tab('Provider').tabIndex).toBe(0);
    expect(tab('Generale').tabIndex).toBe(-1);
    expect(screen.getByText('contenuto provider')).toBeTruthy();

    press('End');
    expect(document.activeElement).toBe(tab('Canali'));
    expect(screen.getByText('contenuto canali')).toBeTruthy();

    press('ArrowRight');
    expect(document.activeElement).toBe(tab('Generale'));

    press('ArrowLeft');
    expect(document.activeElement).toBe(tab('Canali'));

    press('Home');
    expect(document.activeElement).toBe(tab('Generale'));
    expect(tab('Generale').getAttribute('aria-selected')).toBe('true');
  });

  it('sotto sm è una griglia a 3 colonne, da sm una riga sola: nessuna scheda fuori dalla cornice', () => {
    render(<SettingsModal onClose={() => {}} />);
    const cls = screen.getByRole('tablist').className.split(/\s+/);
    expect(cls).toEqual(expect.arrayContaining(['grid', 'grid-cols-3', 'sm:flex']));
    for (const t of screen.getAllByRole('tab')) {
      expect(t.className.split(/\s+/)).toEqual(expect.arrayContaining(['min-w-0', 'sm:flex-1']));
    }
  });
});
