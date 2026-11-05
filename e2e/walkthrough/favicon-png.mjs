// Renders brand/favicon-<name>.svg to a 180 px square PNG (apple-touch-icon; iOS rounds the corners). Usage: node favicon-png.mjs <svg> <png>
import { chromium } from 'playwright';
import fs from 'node:fs';
const [svg, png] = process.argv.slice(2);
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 180, height: 180 } });
await p.setContent(`<body style="margin:0">${fs.readFileSync(svg, 'utf8').replace('rx="14"', 'rx="0"').replace('<svg ', '<svg width="180" height="180" ')}</body>`);
await p.locator('svg').screenshot({ path: png, omitBackground: true });
await b.close();
