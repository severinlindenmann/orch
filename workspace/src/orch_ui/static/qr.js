/* QR Model 2, UTF-8 byte mode, versions 1–40. No ECI or ECC boosting. */
(() => {
  'use strict';

  // ISO/IEC 18004 block parameters, indexed by version minus one.
  const ECC = {
    L: [7,10,15,20,26,18,20,24,30,18,20,24,26,30,22,24,28,30,28,28,28,28,30,30,26,28,30,30,30,30,30,30,30,30,30,30,30,30,30,30],
    M: [10,16,26,18,24,16,18,22,22,26,30,22,22,24,24,28,28,26,26,26,26,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28]
  };
  const BLOCKS = {
    L: [1,1,1,1,1,2,2,2,2,4,4,4,4,4,6,6,6,6,7,8,8,9,9,10,12,12,12,13,14,15,16,17,18,19,19,20,21,22,24,25],
    M: [1,1,1,2,2,4,4,4,5,5,5,8,9,9,10,10,11,13,14,16,17,17,18,20,21,23,25,26,28,29,31,33,35,37,38,40,43,45,47,49]
  };
  const masks = [
    (x,y) => (x+y)%2 === 0,
    (x,y) => y%2 === 0,
    (x,y) => x%3 === 0,
    (x,y) => (x+y)%3 === 0,
    (x,y) => (Math.floor(y/2)+Math.floor(x/3))%2 === 0,
    (x,y) => x*y%2+x*y%3 === 0,
    (x,y) => (x*y%2+x*y%3)%2 === 0,
    (x,y) => ((x+y)%2+x*y%3)%2 === 0
  ];

  function rawWords(version) {
    let bits = (16*version+128)*version+64;
    if (version >= 2) {
      const count = Math.floor(version/7)+2;
      bits -= (25*count-10)*count-55;
      if (version >= 7) bits -= 36;
    }
    return Math.floor(bits/8);
  }

  function prepare(text, {ecc = 'M'} = {}) {
    if (ecc !== 'L' && ecc !== 'M') throw new RangeError('Use ECC L or M.');
    if (typeof text !== 'string') throw new TypeError('QR text must be a string.');
    const bytes = new TextEncoder().encode(text);
    for (let version = 1; version <= 40; version++) {
      const capacity = rawWords(version)-ECC[ecc][version-1]*BLOCKS[ecc][version-1];
      if (4+(version < 10 ? 8 : 16)+bytes.length*8 <= capacity*8) {
        return {bytes, ecc, version, capacity};
      }
    }
    return null;
  }

  // Reed–Solomon over GF(256), primitive polynomial x^8+x^4+x^3+x^2+1.
  function multiply(a, b) {
    let result = 0;
    for (; b; b >>>= 1) {
      if (b & 1) result ^= a;
      a = (a << 1) ^ ((a & 128) ? 0x11d : 0);
    }
    return result;
  }

  function codewords({bytes, ecc, version, capacity}) {
    const bits = [];
    const put = (value, length) => {
      for (let i = length-1; i >= 0; i--) bits.push((value >>> i)&1);
    };
    put(4, 4);
    put(bytes.length, version < 10 ? 8 : 16);
    for (const byte of bytes) put(byte, 8);
    put(0, Math.min(4, capacity*8-bits.length));
    while (bits.length%8) bits.push(0);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) {
      data.push(bits.slice(i, i+8).reduce((value, bit) => value*2+bit, 0));
    }
    for (let pad = 0; data.length < capacity; pad++) data.push(pad%2 ? 0x11 : 0xec);
    const degree = ECC[ecc][version-1], count = BLOCKS[ecc][version-1];
    let generator = [1], root = 1;
    for (let i = 0; i < degree; i++) {
      const next = Array(generator.length+1).fill(0);
      generator.forEach((value, j) => {
        next[j] ^= value;
        next[j+1] ^= multiply(value, root);
      });
      generator = next;
      root = multiply(root, 2);
    }
    const shortLength = Math.floor(capacity/count), shortCount = count-capacity%count;
    const blocks = [], checks = [];
    let offset = 0;
    for (let i = 0; i < count; i++) {
      const length = shortLength+(i >= shortCount ? 1 : 0);
      const block = data.slice(offset, offset+length), remainder = Array(degree).fill(0);
      offset += length;
      for (const byte of block) {
        const factor = byte ^ remainder.shift();
        remainder.push(0);
        for (let j = 0; j < degree; j++) remainder[j] ^= multiply(generator[j+1], factor);
      }
      blocks.push(block);
      checks.push(remainder);
    }
    const result = [];
    for (let i = 0; i <= shortLength; i++) {
      for (const block of blocks) if (i < block.length) result.push(block[i]);
    }
    for (let i = 0; i < degree; i++) for (const check of checks) result.push(check[i]);
    return result;
  }

  // N1 runs, N2 squares, N3 finder-like patterns, N4 dark/light balance.
  function penalty(modules) {
    const size = modules.length;
    let score = 0, dark = 0;
    function line(values) {
      let run = 0, previous, pattern = 0;
      for (let i = 0; i < size; i++) {
        const value = values[i];
        run = value === previous ? run+1 : 1;
        if (run === 5) score += 3;
        else if (run > 5) score++;
        previous = value;
        pattern = ((pattern << 1) | Number(value)) & 0x7ff;
        if (i >= 10 && (pattern === 0x05d || pattern === 0x5d0)) score += 40;
      }
    }
    for (let y = 0; y < size; y++) {
      line(modules[y]);
      line(modules.map(row => row[y]));
      for (let x = 0; x < size; x++) {
        dark += Number(modules[y][x]);
        if (x && y && modules[y][x] === modules[y][x-1] &&
            modules[y][x] === modules[y-1][x] && modules[y][x] === modules[y-1][x-1]) score += 3;
      }
    }
    return score+Math.floor(Math.abs(dark*20-size*size*10)/(size*size))*10;
  }

  function matrix(text, opts) {
    const input = prepare(text, opts);
    if (!input) return null;
    const {version, ecc} = input, size = version*4+17;
    const modules = Array.from({length: size}, () => Array(size).fill(false));
    const reserved = modules.map(row => row.slice());
    function set(x, y, value) {
      modules[y][x] = Boolean(value);
      reserved[y][x] = true;
    }
    for (let i = 0; i < size; i++) {
      set(6, i, i%2 === 0);
      set(i, 6, i%2 === 0);
    }
    for (const [cx, cy] of [[3,3], [size-4,3], [3,size-4]]) {
      for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
        const x = cx+dx, y = cy+dy, distance = Math.max(Math.abs(dx), Math.abs(dy));
        if (x >= 0 && y >= 0 && x < size && y < size) set(x, y, distance !== 2 && distance !== 4);
      }
    }
    if (version >= 2) {
      const count = Math.floor(version/7)+2;
      const step = version === 32 ? 26 : Math.floor((version*4+count*2+1)/(count*2-2))*2;
      const positions = [6];
      for (let p = size-7; positions.length < count; p -= step) positions.splice(1, 0, p);
      for (let i = 0; i < count; i++) for (let j = 0; j < count; j++) {
        if ((i === 0 && (j === 0 || j === count-1)) || (i === count-1 && j === 0)) continue;
        for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
          set(positions[i]+dx, positions[j]+dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
        }
      }
    }
    function format(mask) {
      const data = (ecc === 'L' ? 8 : 0) | mask;
      let remainder = data;
      for (let i = 0; i < 10; i++) remainder = (remainder << 1)^((remainder >>> 9)*0x537);
      const bits = ((data << 10)|remainder)^0x5412;
      const bit = i => (bits >>> i)&1;
      for (let i = 0; i <= 5; i++) set(8, i, bit(i));
      set(8, 7, bit(6)); set(8, 8, bit(7)); set(7, 8, bit(8));
      for (let i = 9; i < 15; i++) set(14-i, 8, bit(i));
      for (let i = 0; i < 8; i++) set(size-1-i, 8, bit(i));
      for (let i = 8; i < 15; i++) set(8, size-15+i, bit(i));
      set(8, size-8, true);
    }
    format(0);
    if (version >= 7) {
      let remainder = version;
      for (let i = 0; i < 12; i++) remainder = (remainder << 1)^((remainder >>> 11)*0x1f25);
      const bits = (version << 12)|remainder;
      for (let i = 0; i < 18; i++) {
        const a = size-11+i%3, b = Math.floor(i/3), bit = (bits >>> i)&1;
        set(a, b, bit); set(b, a, bit);
      }
    }
    const words = codewords(input);
    let index = 0;
    for (let right = size-1; right >= 1; right -= 2) {
      if (right === 6) right--;
      for (let vertical = 0; vertical < size; vertical++) {
        const y = ((right+1)&2) === 0 ? size-1-vertical : vertical;
        for (let j = 0; j < 2; j++) {
          const x = right-j;
          if (!reserved[y][x]) {
            modules[y][x] = index < words.length*8 && Boolean((words[index >>> 3] >>> (7-index%8))&1);
            index++;
          }
        }
      }
    }
    function apply(mask) {
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
        if (!reserved[y][x] && masks[mask](x, y)) modules[y][x] = !modules[y][x];
      }
    }
    let bestMask = 0, bestScore = Infinity;
    for (let mask = 0; mask < 8; mask++) {
      apply(mask);
      format(mask);
      const score = penalty(modules);
      if (score < bestScore) { bestScore = score; bestMask = mask; }
      apply(mask);
    }
    apply(bestMask);
    format(bestMask);
    return {size, modules};
  }

  function svg(text, opts = {}) {
    const result = matrix(text, opts);
    if (!result) return null;
    const ns = 'http://www.w3.org/2000/svg';
    const node = document.createElementNS(ns, 'svg'), path = document.createElementNS(ns, 'path');
    node.setAttribute('viewBox', `0 0 ${result.size+8} ${result.size+8}`);
    node.setAttribute('class', 'qr');
    node.setAttribute('role', 'img');
    node.setAttribute('aria-label', opts.label === undefined ? 'QR code' : opts.label);
    const commands = [];
    result.modules.forEach((row, y) => row.forEach((dark, x) => {
      if (dark) commands.push(`M${x+4} ${y+4}h1v1h-1z`);
    }));
    path.setAttribute('fill', 'currentColor');
    path.setAttribute('d', commands.join(''));
    node.appendChild(path);
    return node;
  }

  const api = {matrix, svg, fits: (text, opts) => prepare(text, opts) !== null};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.OrchQR = api;
})();
