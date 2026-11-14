import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { Fact } from '../../api/memory';
import { FactCard } from './FactCard';

const fact: Fact = {
  id: 7,
  content: 'Il dissipatore X regge 250 W',
  thread_id: null,
  source: 'conversation',
  created_at: '2026-11-14T08:00:00+00:00',
  invalid_at: null,
  superseded_by: null,
  entities: [],
  sensitivity: 'public',
};

function card(extra: Partial<Fact>) {
  const noop = () => {};
  return render(
    <FactCard fact={{ ...fact, ...extra }} known={[]} onSelectEntity={noop} onSave={async () => true} onRestore={noop} onDelete={noop} />,
  );
}

describe('FactCard', () => {
  afterEach(cleanup);

  it('segnala un fatto scritto da contenuto esterno', () => {
    card({ untrusted: true });
    expect(screen.getByTestId('fact-untrusted').textContent).toContain('da contenuto esterno');
  });

  it('non segnala gli altri', () => {
    card({ untrusted: false });
    expect(screen.queryByTestId('fact-untrusted')).toBeNull();
  });
});
