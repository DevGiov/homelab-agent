import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ExecutionTraceViewer } from './ExecutionTraceViewer';

describe('ExecutionTraceViewer: intestazione compressa', () => {
  afterEach(cleanup);
  const trace = [1, 2, 3].map((i) => ({ step_id: `s${i}`, tool_name: `strumento_${i}`, status: 'success' }));

  it('la pillola dei tool resta su una riga e la scritta Mostra cede per prima nei pulsanti stretti', () => {
    render(<ExecutionTraceViewer reasoning="Ragionamento di prova" trace={trace} />);
    const header = screen.getByRole('button', { expanded: false });
    const pill = screen.getByText(/3 tool eseguiti/);
    expect(pill.className.split(/\s+/)).toEqual(expect.arrayContaining(['whitespace-nowrap', 'shrink-0']));
    // Container query sul pulsante: la larghezza che conta è la sua, nel messaggio o nel pannello della diagnostica
    expect(header.className.split(/\s+/)).toContain('@container');
    expect(screen.getByText('Mostra').className.split(/\s+/)).toEqual(expect.arrayContaining(['hidden', '@xs:inline']));
    // Lo stato tra parentesi solo nei pulsanti larghi (28rem): sotto basta la scritta Mostra o Nascondi
    expect(screen.getByText('(compresso)').className.split(/\s+/)).toEqual(expect.arrayContaining(['hidden', '@md:inline']));
  });
});
