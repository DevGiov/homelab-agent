import { describe, expect, it } from 'vitest';
import { runStatusLabel, triggerLabel } from './runLabels';

describe('etichette delle run', () => {
  it('traduce gli stati e i trigger noti', () => {
    expect(runStatusLabel('waiting_approval')).toBe('In attesa di approvazione');
    expect(runStatusLabel('COMPLETED')).toBe('Completata');
    expect(triggerLabel('manual')).toBe('Manuale');
  });

  it('mostra così com’è un valore che non conosce', () => {
    expect(runStatusLabel('rebooting')).toBe('rebooting');
    expect(triggerLabel('mqtt')).toBe('mqtt');
  });
});
