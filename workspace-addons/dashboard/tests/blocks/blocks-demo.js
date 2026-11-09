'use strict';
const column = document.getElementById('fixtures');
for (const fixture of window.BLOCK_FIXTURES) {
  const card = document.createElement('section');
  card.className = 'b-demo-card';
  const heading = document.createElement('h2');
  heading.textContent = fixture.name;
  card.append(heading, window.OrchBlocks.render(fixture.doc, {}).el);
  column.append(card);
}
