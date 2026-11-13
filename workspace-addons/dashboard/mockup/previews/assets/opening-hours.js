export function isOpen(d = new Date()) {
  const h = d.getHours();
  return h >= 7 && h < 17; // Mon-Fri
}
