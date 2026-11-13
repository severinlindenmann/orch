/* orch.blocks/1. Schema rules are mirrored from contracts/blocks.schema.json. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.OrchBlocks = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';
  const LIMITS = Object.freeze({bytes: 65536, blocks: 50, line: 200, short: 64,
    summary: 2000, path: 300, url: 2000, steps: 100, kv: 50, columns: 12,
    rows: 200, cell: 200, series: 4, points: 200, logLines: 200, logLine: 500});
  const schema = {"type":"object","required":["schema","from","blocks"],"additionalProperties":false,"properties":{"schema":{"const":"orch.blocks/1"},"from":{"enum":["job","agent","orch"]},"title":{"$ref":"#/$defs/line"},"blocks":{"type":"array","maxItems":50,"items":{"$ref":"#/$defs/block"}}},"$defs":{"line":{"type":"string","minLength":1,"maxLength":200,"pattern":"^[^\\u0000-\\u001f\\u007f]*$"},"short":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[^\\u0000-\\u001f\\u007f]*$"},"multiline":{"type":"string","maxLength":2000,"pattern":"^[^\\u0000-\\u0008\\u000b-\\u001f\\u007f]*$"},"tone":{"enum":["neutral","good","warn","bad"]},"path":{"type":"string","maxLength":300,"pattern":"^(\\.orch/tickets/t_[a-z0-9]{6,16}/artifacts/)?(?![/\\\\])(?![A-Za-z]:)(?!.*(^|/)\\.)(?!.*\\\\)[^\\u0000-\\u001f\\u007f]+$"},"https":{"type":"string","maxLength":2000,"pattern":"^https://(?![^/?#]*@)[^\\s<>\"'`]+$"},"cell":{"oneOf":[{"type":"null"},{"type":"number"},{"type":"string","maxLength":200,"pattern":"^[^\\u0000-\\u001f\\u007f]*$"}]},"block":{"type":"object","required":["type"],"properties":{"type":{"type":"string","pattern":"^[a-z][a-z0-9-]{0,31}$"}},"allOf":[{"if":{"properties":{"type":{"const":"summary"}}},"then":{"$ref":"#/$defs/summary"}},{"if":{"properties":{"type":{"const":"steps"}}},"then":{"$ref":"#/$defs/steps"}},{"if":{"properties":{"type":{"const":"progress"}}},"then":{"$ref":"#/$defs/progress"}},{"if":{"properties":{"type":{"const":"stat"}}},"then":{"$ref":"#/$defs/stat"}},{"if":{"properties":{"type":{"const":"kv"}}},"then":{"$ref":"#/$defs/kv"}},{"if":{"properties":{"type":{"const":"table"}}},"then":{"$ref":"#/$defs/table"}},{"if":{"properties":{"type":{"const":"file"}}},"then":{"$ref":"#/$defs/file"}},{"if":{"properties":{"type":{"const":"link"}}},"then":{"$ref":"#/$defs/link"}},{"if":{"properties":{"type":{"const":"log"}}},"then":{"$ref":"#/$defs/log"}},{"if":{"properties":{"type":{"const":"chart"}}},"then":{"$ref":"#/$defs/chart"}}]},"summary":{"type":"object","required":["type","text"],"additionalProperties":false,"properties":{"type":{"const":"summary"},"text":{"$ref":"#/$defs/multiline","minLength":1},"tone":{"$ref":"#/$defs/tone"}}},"steps":{"type":"object","required":["type","items"],"additionalProperties":false,"properties":{"type":{"const":"steps"},"items":{"type":"array","minItems":1,"maxItems":100,"items":{"type":"object","required":["label","state"],"additionalProperties":false,"properties":{"label":{"$ref":"#/$defs/line"},"state":{"enum":["waiting","running","done","failed","skipped"]},"note":{"$ref":"#/$defs/line"}}}}}},"progress":{"type":"object","required":["type","label","done","total"],"additionalProperties":false,"properties":{"type":{"const":"progress"},"label":{"$ref":"#/$defs/line"},"done":{"type":"number","minimum":0},"total":{"oneOf":[{"type":"null"},{"type":"number","exclusiveMinimum":0}]},"unit":{"$ref":"#/$defs/short"}}},"stat":{"type":"object","required":["type","label","value"],"additionalProperties":false,"properties":{"type":{"const":"stat"},"label":{"$ref":"#/$defs/line"},"value":{"oneOf":[{"type":"number"},{"$ref":"#/$defs/short"}]},"unit":{"$ref":"#/$defs/short"},"tone":{"$ref":"#/$defs/tone"},"delta":{"$ref":"#/$defs/short"}}},"kv":{"type":"object","required":["type","items"],"additionalProperties":false,"properties":{"type":{"const":"kv"},"items":{"type":"array","minItems":1,"maxItems":50,"items":{"type":"object","required":["key","value"],"additionalProperties":false,"properties":{"key":{"$ref":"#/$defs/line"},"value":{"$ref":"#/$defs/cell"}}}}}},"table":{"type":"object","required":["type","columns","rows"],"additionalProperties":false,"properties":{"type":{"const":"table"},"title":{"$ref":"#/$defs/line"},"columns":{"type":"array","minItems":1,"maxItems":12,"items":{"type":"object","required":["key","label"],"additionalProperties":false,"properties":{"key":{"type":"string","pattern":"^[a-z][a-z0-9_]{0,31}$"},"label":{"$ref":"#/$defs/short"},"kind":{"enum":["text","number","duration","date","tone"]}}}},"rows":{"type":"array","maxItems":200,"items":{"type":"object","maxProperties":12,"propertyNames":{"pattern":"^[a-z][a-z0-9_]{0,31}$"},"additionalProperties":{"$ref":"#/$defs/cell"}}},"total_rows":{"type":"integer","minimum":0}}},"file":{"type":"object","required":["type","path"],"additionalProperties":false,"properties":{"type":{"const":"file"},"path":{"$ref":"#/$defs/path"},"label":{"$ref":"#/$defs/line"},"size":{"type":"integer","minimum":0},"preview":{"const":"image"}}},"link":{"type":"object","required":["type","url","label"],"additionalProperties":false,"properties":{"type":{"const":"link"},"url":{"$ref":"#/$defs/https"},"label":{"$ref":"#/$defs/line"}}},"log":{"type":"object","required":["type","lines"],"additionalProperties":false,"properties":{"type":{"const":"log"},"title":{"$ref":"#/$defs/line"},"lines":{"type":"array","maxItems":200,"items":{"type":"string","maxLength":500,"pattern":"^[^\\u0000-\\u0008\\u000a-\\u001f\\u007f]*$"}},"cut":{"type":"integer","minimum":0}}},"chart":{"type":"object","required":["type","kind","series"],"additionalProperties":false,"properties":{"type":{"const":"chart"},"kind":{"enum":["line","bar"]},"title":{"$ref":"#/$defs/line"},"x_label":{"$ref":"#/$defs/short"},"y_label":{"$ref":"#/$defs/short"},"series":{"type":"array","minItems":1,"maxItems":4,"items":{"type":"object","required":["name","points"],"additionalProperties":false,"properties":{"name":{"$ref":"#/$defs/short"},"points":{"type":"array","maxItems":200,"items":{"type":"array","prefixItems":[{"oneOf":[{"type":"number"},{"$ref":"#/$defs/short"}]},{"type":["number","null"]}],"minItems":2,"maxItems":2}}}}}}}}};
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const number = v => typeof v === 'number' && Number.isFinite(v);
  const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
  function matches(v, rule) {
    if (rule.$ref && !matches(v, schema.$defs[rule.$ref.split('/').pop()])) return false;
    if (own(rule, 'const') && v !== rule.const) return false;
    if (rule.enum && !rule.enum.includes(v)) return false;
    if (rule.type) {
      const types = Array.isArray(rule.type) ? rule.type : [rule.type];
      if (!types.some(t => t === 'null' ? v === null : t === 'object' ? object(v) :
        t === 'array' ? Array.isArray(v) : t === 'number' ? number(v) :
        t === 'integer' ? Number.isInteger(v) : typeof v === t)) return false;
    }
    if (rule.oneOf && rule.oneOf.filter(r => matches(v, r)).length !== 1) return false;
    if (rule.allOf && !rule.allOf.every(r => matches(v, r))) return false;
    if (rule.if && matches(v, rule.if) && !matches(v, rule.then)) return false;
    if (typeof v === 'string') {
      const length = [...v].length;
      if (length < (rule.minLength || 0) || length > (rule.maxLength ?? Infinity)) return false;
      // All patterns are bounded by a field limit or the compact document limit.
      if (rule.pattern && !new RegExp(rule.pattern, 'u').test(v)) return false;
    }
    if (number(v) && (v < (rule.minimum ?? -Infinity) || v <= (rule.exclusiveMinimum ?? -Infinity))) return false;
    if (Array.isArray(v)) {
      if (v.length < (rule.minItems || 0) || v.length > (rule.maxItems ?? Infinity)) return false;
      if (rule.items && !v.every(x => matches(x, rule.items))) return false;
      if (rule.prefixItems && !rule.prefixItems.every((r, i) => i >= v.length || matches(v[i], r))) return false;
    }
    if (object(v)) {
      if (rule.required && !rule.required.every(k => own(v, k))) return false;
      const keys = Object.keys(v);
      if (keys.length > (rule.maxProperties ?? Infinity)) return false;
      for (const k of keys) {
        if (rule.propertyNames && !matches(k, rule.propertyNames)) return false;
        if (rule.properties && own(rule.properties, k)) {
          if (!matches(v[k], rule.properties[k])) return false;
        } else if (rule.additionalProperties === false) return false;
        else if (object(rule.additionalProperties) && !matches(v[k], rule.additionalProperties)) return false;
      }
    }
    return true;
  }
  function raw(doc) {
    try { return JSON.stringify(doc) ?? 'No document'; }
    catch (_) { return 'Could not read the document'; }
  }
  function validate(doc) {
    const errors = [];
    let json;
    try { json = JSON.stringify(doc); } catch (_) { errors.push('The document must be JSON.'); }
    if (json === undefined) errors.push('The document must be JSON.');
    if (json !== undefined) {
      let bytes = 0;
      for (const c of json) { const n = c.codePointAt(0); bytes += n < 128 ? 1 : n < 2048 ? 2 : n < 65536 ? 3 : 4; }
      if (bytes > LIMITS.bytes) errors.push('The document is larger than 64 KB.');
    }
    if (!errors.length && !matches(doc, schema)) errors.push('The document does not follow orch.blocks/1.');
    return {ok: errors.length === 0, errors};
  }
  function isSafeHttps(url) {
    return typeof url === 'string' && [...url].length <= LIMITS.url &&
      /^https:\/\/(?![^/?#]*@)[^\s<>"'`]+$/u.test(url);
  }
  function duration(n) {
    return n >= 60 ? Math.floor(n / 60) + ' min ' + String(n % 60) + ' s' : String(n) + ' s';
  }
  function size(n) {
    if (n < 1024) return String(n) + ' bytes';
    const value = n / (n < 1048576 ? 1024 : 1048576);
    return (value < 10 ? value.toFixed(1) : String(Math.round(value))) + (n < 1048576 ? ' KB' : ' MB');
  }
  // Normalize before subtracting, so even opposite finite extremes cannot overflow.
  function scale(v, min, max) {
    if (min === max) return 0.5;
    const d = Math.max(Math.abs(min), Math.abs(max), 1);
    return (v / d - min / d) / (max / d - min / d);
  }
  function render(doc, opts) {
    opts = opts || {};
    const d = opts.document || document;
    function el(tag, cls, text, attrs, svg) {
      const e = svg ? d.createElementNS('http://www.w3.org/2000/svg', tag) : d.createElement(tag);
      if (cls) { if (svg) e.setAttribute('class', cls); else e.className = cls; }
      if (text !== undefined) e.textContent = String(text);
      if (attrs) for (const k of Object.keys(attrs)) e.setAttribute(k, String(attrs[k]));
      return e;
    }
    function width(e, value) {
      if (number(value)) e.style.setProperty('width', Math.max(0, Math.min(100, value)) + '%');
      return e;
    }
    const result = validate(doc);
    const root = el('div', result.ok ? 'blocks' : 'blocks blocks-invalid');
    let fallbacks = 0;
    if (!result.ok) {
      const details = el('details');
      details.append(el('summary', '', 'Details'), el('pre', '', (result.errors.join('\n') + '\n' + raw(doc)).slice(0, 4000)));
      root.append(el('p', '', "These results can't be shown"), details);
      return {el: root, valid: false, errors: result.errors, fallbacks};
    }
    const muted = text => el('p', 'b-muted', text);
    const valueText = v => v == null ? '–' : String(v);
    function chart(b) {
      const fig = el('figure', 'b-chart');
      if (b.title) fig.append(el('figcaption', '', b.title));
      const alternative = el('table', 'b-sr sr-only');
      const head = el('thead'), header = el('tr');
      for (const label of ['Series', b.x_label || 'Position', b.y_label || 'Value']) header.append(el('th', '', label, {scope: 'col'}));
      head.append(header); alternative.append(head);
      const body = el('tbody');
      for (const s of b.series) for (const [x, y] of s.points) {
        const row = el('tr');
        for (const v of [s.name, x, y === null ? 'no value' : y]) row.append(el('td', '', v));
        body.append(row);
      }
      alternative.append(body);
      if (b.kind === 'line') {
        const svg = el('svg', '', undefined, {viewBox: '0 0 300 90', role: 'img', 'aria-label': b.title || 'Values by series', 'aria-hidden': 'true'}, true);
        const points = b.series.flatMap(s => s.points);
        const ys = points.filter(p => p[1] !== null).map(p => p[1]);
        const xs = points.map(p => p[0]);
        const numeric = xs.every(number);
        const xmin = numeric && xs.length ? Math.min(...xs) : 0, xmax = numeric && xs.length ? Math.max(...xs) : 1;
        const ymin = ys.length ? Math.min(...ys) : 0, ymax = ys.length ? Math.max(...ys) : 1;
        b.series.forEach((s, index) => {
          let segment = [];
          function flush() {
            if (segment.length) svg.append(el('polyline', 's' + index, undefined, {points: segment.join(' ')}, true));
            segment = [];
          }
          s.points.forEach(([x, y], i) => {
            if (y === null) { flush(); return; }
            const px = numeric ? scale(x, xmin, xmax) : s.points.length === 1 ? 0.5 : i / (s.points.length - 1);
            segment.push((6 + px * 288).toFixed(2) + ',' + (84 - scale(y, ymin, ymax) * 78).toFixed(2));
          });
          flush();
        });
        fig.append(svg);
        const legend = el('ul', 'b-legend', undefined, {'aria-hidden': 'true'});
        b.series.forEach((s, index) => { const li = el('li'); li.append(el('i', 's' + index), el('span', '', s.name)); legend.append(li); });
        fig.append(legend);
        if (xs.length) {
          const first = xs[0], last = xs[xs.length - 1];
          const ends = el('div', 'b-axis', undefined, {'aria-hidden': 'true'});
          ends.append(el('span', '', first), el('span', '', ys.length ? 'Lowest ' + ymin + ', highest ' + ymax : ''), el('span', '', last));
          fig.append(ends);
        }
      } else {
        const bars = el('div', 'bars', undefined, {'aria-hidden': 'true'});
        b.series.forEach((s, index) => {
          if (b.series.length > 1) bars.append(el('h4', 'b-muted', s.name));
          const max = Math.max(1, ...s.points.map(p => Math.abs(p[1] || 0)));
          for (const [x, y] of s.points) {
            const row = el('div', 'r');
            row.append(el('span', '', x), width(el('i', 's' + index), Math.abs(y || 0) / max * 100), el('span', '', y === null ? 'no value' : y));
            bars.append(row);
          }
        });
        fig.append(bars);
      }
      const caption = b.y_label && b.x_label ? b.y_label + ' by ' + b.x_label : b.y_label || b.x_label;
      if (caption) fig.append(el('p', 'b-muted b-axiscap', caption, {'aria-hidden': 'true'}));
      fig.append(alternative);
      return fig;
    }
    function renderBlock(b) {
      let box;
      switch (b.type) {
        case 'summary': {
          const tone = b.tone || 'neutral';
          box = el('div', 'b-sum ' + tone);
          box.append(el('span', '', {good: '✓', warn: '⚠', bad: '✕', neutral: '•'}[tone], {'aria-hidden': 'true'}));
          if (tone !== 'neutral') box.append(el('span', 'sr-only', {good: 'Good:', warn: 'Warning:', bad: 'Problem:'}[tone]));
          box.append(el('span', '', b.text)); return box;
        }
        case 'steps':
          box = el('ol', 'b-steps');
          for (const s of b.items) {
            const row = el('li', s.state);
            row.append(el('span', '', {waiting: '○', running: '◌', done: '✓', failed: '✕', skipped: '–'}[s.state], {'aria-hidden': 'true'}),
              el('span', '', s.label), el('span', 'b-muted', s.note || {waiting: 'Waiting', running: 'Running', done: 'Done', failed: 'Failed', skipped: 'Skipped'}[s.state]));
            box.append(row);
          }
          return box;
        case 'progress': {
          box = el('div', 'b-prog' + (b.total === null ? ' b-indet' : ''));
          const line = el('div', 'l');
          const unit = b.unit ? ' ' + b.unit : '';
          line.append(el('span', '', b.label), el('span', '', b.total === null ? b.done + unit + ' so far' : b.done + ' of ' + b.total + unit));
          const attrs = {role: 'progressbar', 'aria-label': b.label, 'aria-valuemin': 0};
          if (b.total !== null) { attrs['aria-valuemax'] = b.total; attrs['aria-valuenow'] = b.done; }
          const bar = el('div', 'bar', undefined, attrs);
          bar.append(b.total === null ? el('i') : width(el('i'), b.done >= b.total ? 100 : Math.round(b.done / b.total * 100)));
          box.append(line, bar); return box;
        }
        case 'stat':
          box = el('div', 'b-stat ' + (b.tone || 'neutral'));
          box.append(el('span', '', b.label), el('strong', '', String(b.value) + (b.unit ? ' ' + b.unit : '')));
          if (b.delta) box.append(muted(b.delta)); return box;
        case 'kv':
          box = el('dl', 'b-kv');
          for (const item of b.items) box.append(el('dt', '', item.key), el('dd', '', valueText(item.value)));
          return box;
        case 'table': {
          box = el('div', 'b-table');
          const table = el('table'), head = el('thead'), row = el('tr'), body = el('tbody');
          if (b.title) table.append(el('caption', '', b.title));
          for (const c of b.columns) row.append(el('th', c.kind === 'number' ? 'num' : '', c.label, {scope: 'col'}));
          head.append(row); table.append(head);
          for (const r of b.rows) {
            const tr = el('tr');
            for (const c of b.columns) {
              const v = own(r, c.key) ? r[c.key] : null;
              tr.append(el('td', c.kind === 'number' ? 'num' : '', c.kind === 'duration' && number(v) ? duration(v) : valueText(v)));
            }
            body.append(tr);
          }
          table.append(body); box.append(table);
          if (!b.rows.length) box.append(el('p', 'b-empty', 'Nothing to show'));
          if (b.total_rows > b.rows.length) box.append(muted('First ' + b.rows.length + ' of ' + b.total_rows));
          return box;
        }
        case 'file': {
          box = el('div', 'b-file');
          const name = b.label || b.path.split('/').pop();
          box.append(el('span', '', '▤', {'aria-hidden': 'true'}), el('span', '', name));
          if (b.size !== undefined) box.append(muted(size(b.size)));
          let url = null;
          if (typeof opts.fileUrl === 'function') {
            try { url = opts.fileUrl(b.path); } catch (_) { /* A host may refuse access. */ }
            if (typeof url !== 'string' || !(/^(\/(?![/\\])|blob:)/u.test(url)) || /[\u0000-\u0020\\]/u.test(url)) url = null;
            if (url === null) box.append(muted('File not available'));
          }
          if (url && b.preview === 'image' && /\.(png|jpe?g|gif|webp)$/i.test(b.path) && (b.size === undefined || b.size <= 2 * 1024 * 1024))
          {
            const img = el('img', 'b-pic', undefined, {src: url, alt: name, loading: 'lazy'});
            // A picture that fails to load is replaced by a note, never a broken-image icon.
            if (typeof img.addEventListener === 'function') img.addEventListener('error', () => { img.setAttribute('hidden', ''); box.append(muted('File not available')); });
            box.append(img);
          }
          return box;
        }
        case 'link':
          if (!isSafeHttps(b.url)) return el('span', 'b-link', b.label);
          box = el('a', 'btn b-link', b.label, {href: b.url, target: '_blank', rel: 'noopener noreferrer'});
          box.append(el('span', 'sr-only', ' (opens in the browser)')); return box;
        case 'log':
          box = el('div', 'b-log', undefined, {role: 'region', 'aria-label': b.title || 'Output'});
          if (b.title) box.append(el('h4', '', b.title));
          if (b.cut > 0) box.append(el('p', 'b-cut', '… ' + b.cut + ' earlier lines left out'));
          box.append(el('pre', '', b.lines.join('\n'))); return box;
        case 'chart': return chart(b);
        default: fallbacks++; return el('div', 'b-fallback', "Can't show this here");
      }
    }
    if (doc.title) root.append(el('h3', 'b-title', doc.title));
    root.append(el('p', 'b-from', {job: 'Reported by the job', agent: 'Proof by the helper', orch: 'Worked out by orch'}[doc.from]));
    for (const b of doc.blocks) root.append(renderBlock(b));
    return {el: root, valid: true, errors: [], fallbacks};
  }
  return {validate, render, LIMITS, isSafeHttps};
});
