'use strict';
// The kit's one ticket-state rule (ORCH-71) and the helper meta line, for tests that run Focus code without a browser.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const w = {};
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.js'), 'utf8'), vm.createContext({window: w}));
module.exports = {ticketState: w.UI.ticketState, helperMeta: w.UI.helperMeta};
