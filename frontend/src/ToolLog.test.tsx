import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { jsonResponse, mockBackend } from './test/backend';
import { ToolLog } from './ToolLog';

describe('ToolLog: pulsante del pannello compresso', () => {
  beforeEach(() => {
    mockBackend({}, [[/.*/, () => jsonResponse({ pending: [] })]]);
  });
  afterEach(cleanup);

  const toggle = () => screen.getByRole('button', { name: "Diagnostica dell'agente" });

  it('compresso ha un nome, aria-expanded falso, e impila icona e freccia nella striscia', () => {
    const onToggle = vi.fn();
    render(<ToolLog isOpen={false} onToggle={onToggle} />);
    const button = toggle();
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(button.className.split(/\s+/)).toEqual(expect.arrayContaining(['md:flex-col', 'md:justify-center']));
    // Il testo resta per gli screen reader, fuori dalla larghezza della striscia
    expect(screen.getByText("Diagnostica dell'agente").className).toBe('sr-only');
    expect(button.parentElement!.className.split(/\s+/)).toEqual(expect.arrayContaining(['md:p-0', 'md:h-14']));
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it('aperto mostra il titolo in riga con aria-expanded vero', () => {
    render(<ToolLog isOpen onToggle={() => {}} />);
    const button = toggle();
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(button.className.split(/\s+/)).not.toContain('md:flex-col');
    expect(screen.getByText("Diagnostica dell'agente").className).not.toContain('sr-only');
  });
});
