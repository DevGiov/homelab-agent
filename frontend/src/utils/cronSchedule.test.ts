import { describe, expect, it } from 'vitest';
import { buildTriggers, describeSchedule, parseCron, toCron } from './cronSchedule';

describe('parseCron / toCron', () => {
  it.each([
    ['42 10 * * *', 'daily'],
    ['0 8 * * 1', 'weekly'],
    ['0 8 * * 7', 'weekly'],
    ['15 */6 * * *', 'hourly'],
  ])('%s si apre nei controlli guidati (%s) e torna uguale', (expr, frequency) => {
    const schedule = parseCron(expr);
    expect(schedule.frequency).toBe(frequency);
    expect(toCron(schedule)).toBe(expr.replace(/ 7$/, ' 0'));
  });

  it.each(['0 8 * * 1-5', '0 8 1 * *', '*/15 * * * *', '0 */5 * * *', '0 8,20 * * *', '@daily', '0 25 * * *'])(
    '%s resta cron avanzato e non viene alterato',
    (expr) => {
      const schedule = parseCron(expr);
      expect(schedule.frequency).toBe('custom');
      expect(toCron(schedule)).toBe(expr);
    }
  );

  it('senza cron parte da ogni giorno alle 08:00', () => {
    expect(toCron(parseCron(undefined))).toBe('0 8 * * *');
  });

  it('descrive la pianificazione con il fuso del trigger', () => {
    expect(describeSchedule(parseCron('5 7 * * 0'), 'UTC')).toBe('Ogni Domenica alle ore 07:05 (fuso UTC).');
  });
});

describe('buildTriggers', () => {
  const existing = [
    { id: 'trg-cron', type: 'cron', cron_expression: '0 12 * * *', timezone: 'UTC', enabled: true },
    { id: 'trg-hook', type: 'webhook', webhook_token: 'tok', enabled: true },
    { id: 'trg-manual', type: 'manual', enabled: true },
  ];

  it('aggiorna cron e webhook mantenendo id e conservando gli altri trigger', () => {
    expect(
      buildTriggers(existing, { enabled: true, expression: '0 9 * * *', timezone: 'UTC' }, { enabled: true, token: 'tok' })
    ).toEqual([
      { id: 'trg-cron', type: 'cron', cron_expression: '0 9 * * *', timezone: 'UTC', enabled: true },
      { id: 'trg-hook', type: 'webhook', webhook_token: 'tok', enabled: true },
      { id: 'trg-manual', type: 'manual', enabled: true },
    ]);
  });

  it('disattivando cron e webhook restano gli altri trigger', () => {
    expect(buildTriggers(existing, { enabled: false, expression: '', timezone: 'UTC' }, { enabled: false, token: '' })).toEqual([
      { id: 'trg-manual', type: 'manual', enabled: true },
    ]);
  });

  it('senza alcun trigger aggiunge l\'avvio manuale', () => {
    expect(buildTriggers([], { enabled: false, expression: '', timezone: 'UTC' }, { enabled: false, token: '' })).toEqual([
      { id: 'trg_manual', type: 'manual', enabled: true },
    ]);
  });
});
