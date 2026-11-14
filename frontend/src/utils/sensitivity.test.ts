import { describe, expect, it } from 'vitest';
import { describeDestination, describeReason, describeTag, joinTags, parseFlowCapability, serverScopes } from './sensitivity';

describe('sensibilità: etichette', () => {
  it('unisce prendendo la più alta e i motivi di quella', () => {
    const tag = joinTags(
      { label: 'internal', reasons: ['tool:proxmox-mcp__list_containers'] },
      { label: 'private', reasons: ['memoria:fatto'] },
      { label: 'public', untrusted: true, reasons: ['untrusted:web_prefetch'] }
    );
    expect(tag).toEqual({ label: 'private', untrusted: true, reasons: ['memoria:fatto', 'untrusted:web_prefetch'] });
    expect(joinTags(null, undefined)).toEqual({ label: 'public', untrusted: false, reasons: [] });
  });

  it('descrive i motivi in italiano', () => {
    expect(describeReason('memoria:profilo')).toBe('il profilo utente');
    expect(describeReason('tool:web_search')).toBe('risultato di web_search');
    expect(describeReason('messaggio:iban')).toBe('un IBAN nel messaggio');
    expect(describeReason('conversazione:private')).toBe('il livello scelto per la conversazione');
    expect(describeReason('untrusted:tool:email_fetch_unread')).toBe('contenuto non attendibile: risultato di email_fetch_unread');
    expect(describeReason('qualcosa:di:nuovo')).toBe('qualcosa:di:nuovo');
    expect(describeTag({ label: 'private', reasons: ['memoria:fatto', 'memoria:fatto', 'untrusted:web_prefetch'] })).toEqual({
      reasons: ['un fatto della memoria'],
      untrusted: ['contenuto non attendibile: pagine web della ricerca preventiva'],
    });
  });

  it('riconosce la capability di un’uscita di dati', () => {
    expect(parseFlowCapability('flow:search:web:private')).toEqual({ destination: 'search:web', label: 'private' });
    expect(parseFlowCapability('flow:http:api.example.org:internal')).toEqual({ destination: 'http:api.example.org', label: 'internal' });
    expect(parseFlowCapability('net:example.org')).toBeNull();
    expect(parseFlowCapability('flow:search:web:boh')).toBeNull();
    expect(parseFlowCapability(undefined)).toBeNull();
    expect(describeDestination('search:web')).toBe('la ricerca web (motori pubblici)');
    expect(describeDestination('mcp:scout')).toBe('il server MCP scout');
  });

  it('ricava i server MCP dai nomi dei tool', () => {
    expect(serverScopes(['b__x', 'a__y', 'a__z', 'senza_prefisso'])).toEqual(['a', 'b']);
  });
});
