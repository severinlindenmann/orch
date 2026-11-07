const words = terms => new RegExp(`\\b(?:${terms.join('|')})\\b`, 'gi');
export const RULES = [
  { rule: 'vpn-product', pattern: words(['netbird', 'wireguard', 'tailscale', 'zerotier']) },
  { rule: 'never-word', pattern: words(['request', 'job', 'issue', 'subtask', 'todo', 'epic', 'bot', 'peer', 'node', 'scheduler', 'cron', 'schedules?', 'evidence', 'over to you', 'human', 'recommended', 'cli']) },
  { rule: 'jargon', pattern: /\b(?:claim|claimed|revision|adapter|payload|token|traceback|undefined|null|NaN|TODO|lorem)\b|\bext\.|\[object Object\]|\{\{|\}\}/gi },
  { rule: 'cli-command', pattern: /\borch\s+(?:relay|ticket|run|publish|answer|ask|check|start|stop|status|addon|config|init|ref|update|automation|dashboard|focus)\b/g },
  { rule: 'typed-word', pattern: /\btype\s+(?:the\s+word|DELETE)\b/gi },
];
export function lintText(text, ctx = {}) {
  const allow = new Set((ctx.allow || []).map(x => x.toLowerCase()));
  return [...RULES, ...(ctx.rules || [])].flatMap(({ rule, pattern }) => {
    const re = new RegExp(pattern.source, pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`);
    return [...String(text).matchAll(re)].filter(m => !allow.has(m[0].toLowerCase())).map(m => ({
      rule, text: m[0], where: text.slice(Math.max(0, m.index - 20), m.index + m[0].length + 20),
    }));
  });
}
const TERMS = ['Ticket', 'Task', 'Sub-ticket', 'Needs you', 'Question', 'Proof', 'Repeat', 'Repeats', 'Add', 'Create', 'New', 'Save', 'Remove', 'Delete', 'Close', 'Done', 'Doing', 'To do', 'Open', 'Waiting'];
export function termTable(texts) {
  const text = Array.isArray(texts) ? texts.join('\n') : String(texts);
  return Object.fromEntries(TERMS.map(term => [term, [...text.matchAll(new RegExp(`\\b${term}\\b`, 'gi'))].length]));
}
