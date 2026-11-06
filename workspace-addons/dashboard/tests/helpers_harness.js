// node helpers_harness.js <helpers.js> <json: {fn, args}>  -> prints JSON of the result
const H = require(process.argv[2]);
const {fn, args} = JSON.parse(process.argv[3]);
console.log(JSON.stringify(H[fn](...args)));
