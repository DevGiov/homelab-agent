import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import React, { useRef, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { useModalFocus } from './useModalFocus';

const Dialog: React.FC<{ label: string; onClose?: () => void; children?: React.ReactNode }> = ({ label, onClose, children }) => {
  const ref = useRef<HTMLDivElement>(null);
  useModalFocus(ref, { onClose });
  return (
    <div ref={ref} role="dialog" aria-modal="true" aria-label={label}>
      <button type="button">Primo {label}</button>
      <input aria-label={`Campo ${label}`} />
      <button type="button" disabled>
        Spento {label}
      </button>
      {children}
      <button type="button" onClick={onClose}>
        Chiudi {label}
      </button>
    </div>
  );
};

/** Un pulsante che apre la finestra, come nell'app: il focus è sul pulsante quando la finestra compare. */
const Harness: React.FC<{ closable?: boolean }> = ({ closable = true }) => {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Apri
      </button>
      {open && <Dialog label="A" onClose={closable ? () => setOpen(false) : undefined} />}
      <button type="button">Fuori</button>
    </>
  );
};

const openWithKeyboard = (name: string) => {
  const opener = screen.getByRole('button', { name });
  act(() => opener.focus());
  fireEvent.click(opener);
  return opener;
};
const tab = (shift = false) => fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Tab', shiftKey: shift });

describe('useModalFocus', () => {
  afterEach(cleanup);

  it("all'apertura porta il focus sul primo elemento della finestra", () => {
    render(<Harness />);
    openWithKeyboard('Apri');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Primo A' }));
  });

  it('Tab e Maiusc+Tab girano dentro la finestra, saltando i controlli disattivati', () => {
    render(<Harness />);
    openWithKeyboard('Apri');
    const first = screen.getByRole('button', { name: 'Primo A' });
    const last = screen.getByRole('button', { name: 'Chiudi A' });

    tab(true);
    expect(document.activeElement).toBe(last);
    tab();
    expect(document.activeElement).toBe(first);
  });

  it('riporta dentro il focus finito fuori dalla finestra', () => {
    render(<Harness />);
    openWithKeyboard('Apri');
    act(() => screen.getByRole('button', { name: 'Fuori' }).focus());
    tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Primo A' }));
  });

  it('Escape chiude e il focus torna al pulsante che ha aperto la finestra', () => {
    render(<Harness />);
    const opener = openWithKeyboard('Apri');
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('anche la chiusura con un pulsante restituisce il focus', () => {
    render(<Harness />);
    const opener = openWithKeyboard('Apri');
    fireEvent.click(screen.getByRole('button', { name: 'Chiudi A' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('senza onClose Escape non chiude', () => {
    render(<Harness closable={false} />);
    openWithKeyboard('Apri');
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeTruthy();
  });

  it('con due finestre aperte Tab ed Escape valgono per quella in cima', () => {
    const Nested: React.FC = () => {
      const [inner, setInner] = useState(false);
      const [outer, setOuter] = useState(true);
      return outer ? (
        <Dialog label="Esterna" onClose={() => setOuter(false)}>
          <button type="button" onClick={() => setInner(true)}>
            Conferma
          </button>
          {inner && <Dialog label="Interna" onClose={() => setInner(false)} />}
        </Dialog>
      ) : null;
    };
    render(<Nested />);
    openWithKeyboard('Conferma');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Primo Interna' }));

    tab(true);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Chiudi Interna' }));

    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Interna' })).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Esterna' })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Conferma' }));
  });
});

describe('ConfirmDialog', () => {
  afterEach(cleanup);

  const ConfirmHarness: React.FC<{ onAnswer: (ok: boolean) => void }> = ({ onAnswer }) => {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Elimina conversazione
        </button>
        <ConfirmDialog
          request={open ? { message: 'Eliminare?' } : null}
          onAnswer={(ok) => {
            onAnswer(ok);
            setOpen(false);
          }}
        />
      </>
    );
  };

  it('mette a fuoco Annulla, non il pulsante distruttivo; tiene il Tab dentro, Escape annulla e il focus torna indietro', () => {
    const onAnswer = vi.fn();
    render(<ConfirmHarness onAnswer={onAnswer} />);
    const opener = openWithKeyboard('Elimina conversazione');

    const cancel = screen.getByRole('button', { name: 'Annulla' });
    const confirm = screen.getByRole('button', { name: 'Elimina' });
    // Un Invio appena aperta la finestra va ad Annulla. Il Tab tra i due pulsanti lo fa il browser; la finestra fa girare i bordi
    expect(document.activeElement).toBe(cancel);
    tab(true);
    expect(document.activeElement).toBe(confirm);
    tab();
    expect(document.activeElement).toBe(cancel);

    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(onAnswer).toHaveBeenCalledWith(false);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});
