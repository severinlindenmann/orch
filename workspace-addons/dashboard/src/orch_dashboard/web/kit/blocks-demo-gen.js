'use strict';
const fs = require('node:fs');
const path = require('node:path');
const folder = path.resolve(__dirname, '../../../../../../contracts/vectors/blocks');
const fixtures = fs.readdirSync(folder).filter(n => /^valid-.*\.json$/.test(n)).sort().map(name => ({
  name, doc: JSON.parse(fs.readFileSync(path.join(folder, name), 'utf8')).doc
}));
fs.writeFileSync(path.join(__dirname, 'blocks-demo-data.js'), 'window.BLOCK_FIXTURES = ' + JSON.stringify(fixtures, null, 2) + ';\n');
