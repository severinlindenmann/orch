/* Files page mockup (ORCH-654, the look of ORCH-606 draft D): demo data only, read by mock-api.js. Workspace "Demo", a small café company (Anna, Ben, Severin).
   Every file: name, folder, size (bytes), changed, who, optional ticket, and for text kinds a few lines of text
   so the search can look inside. The other fields are what the kit's result widgets (results.js) read. */
(() => {
  'use strict';
  const uri = svg => 'data:image/svg+xml,' + encodeURIComponent(svg);
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Simple picture stand-ins (no outside images). Colours here are picture content, not interface colours.
  const MOTIF = {
    terrace: '<rect y="150" width="320" height="90" fill="#8a7a63"/><path d="M60 150 160 70l100 80z" fill="#c9553f"/><rect x="157" y="70" width="6" height="120" fill="#4a3b2c"/><ellipse cx="160" cy="190" rx="60" ry="10" fill="#e8dcc6"/><circle cx="262" cy="46" r="20" fill="#f6d77a"/>',
    cup: '<circle cx="160" cy="120" r="84" fill="#f1ece3"/><circle cx="160" cy="120" r="66" fill="#a8744b"/><path d="M160 80c-22 14-22 40 0 66 22-26 22-52 0-66z" fill="#f3e3cf"/><path d="M160 96c-10 8-10 22 0 36 10-14 10-28 0-36z" fill="#a8744b"/>',
    people: '<rect y="170" width="320" height="70" fill="#5d6b5a"/><circle cx="100" cy="110" r="26" fill="#e6c3a3"/><rect x="70" y="140" width="60" height="80" rx="16" fill="#3f6f8f"/><circle cx="160" cy="100" r="28" fill="#d9a987"/><rect x="128" y="132" width="64" height="90" rx="16" fill="#c9553f"/><circle cx="222" cy="112" r="25" fill="#eecfb4"/><rect x="193" y="141" width="58" height="80" rx="16" fill="#4f8a6b"/>',
    bake: '<rect y="160" width="320" height="80" fill="#6b4f3a"/><path d="M60 150c10-50 80-60 100-10-30-14-66-8-100 10z" fill="#d99a4e"/><path d="M170 160c14-54 90-56 104-4-30-18-70-14-104 4z" fill="#c98a3e"/><path d="M110 190c12-36 70-40 86-4-26-10-56-8-86 4z" fill="#e0a85c"/>',
    shop: '<rect y="190" width="320" height="50" fill="#57534c"/><rect x="60" y="70" width="200" height="120" fill="#e9dfcf"/><path d="M50 70h220l-14 34H64z" fill="#c9553f"/><rect x="84" y="118" width="60" height="50" fill="#7fb0c9"/><rect x="176" y="118" width="46" height="72" fill="#6b4f3a"/>',
    latte: '<rect y="170" width="320" height="70" fill="#7a5a3f"/><path d="M110 70h100l-12 110h-76z" fill="#f1ece3"/><path d="M114 90h92l-6 60h-80z" fill="#e08a3c"/><circle cx="250" cy="170" r="26" fill="#e3792b"/><rect x="247" y="138" width="6" height="12" fill="#4f7a3a"/>',
    card: '<rect x="90" y="20" width="140" height="200" rx="6" fill="#f6f1e7"/><rect x="112" y="44" width="96" height="10" fill="#3b2f25"/><rect x="112" y="72" width="80" height="4" fill="#8b7d6d"/><rect x="112" y="86" width="96" height="4" fill="#8b7d6d"/><rect x="112" y="100" width="64" height="4" fill="#8b7d6d"/><rect x="112" y="128" width="88" height="4" fill="#8b7d6d"/><rect x="112" y="142" width="70" height="4" fill="#8b7d6d"/><circle cx="160" cy="184" r="14" fill="#c9553f"/>',
    cover: '<rect x="80" y="14" width="160" height="212" rx="4" fill="#dfeadd"/><circle cx="160" cy="96" r="44" fill="#f2b7b0"/><path d="M160 66c-14 10-14 30 0 52 14-22 14-42 0-52z" fill="#f8e6e2"/><rect x="108" y="164" width="104" height="10" fill="#2f4a3a"/><rect x="124" y="186" width="72" height="5" fill="#5f7a69"/>',
    logo: '<circle cx="160" cy="120" r="78" fill="#173c33"/><path d="M118 100h72v26a36 36 0 0 1-72 0z" fill="#61d5b8"/><path d="M190 106h10a12 12 0 0 1 0 24h-10" fill="none" stroke="#61d5b8" stroke-width="8"/><path d="M140 84c0-8 8-8 8-16m12 16c0-8 8-8 8-16" fill="none" stroke="#61d5b8" stroke-width="5" stroke-linecap="round"/>',
    header: '<rect width="320" height="240" fill="#f3e3cf"/><rect y="150" width="320" height="90" fill="#e08a3c"/><rect x="40" y="60" width="150" height="14" fill="#3b2f25"/><rect x="40" y="88" width="110" height="8" fill="#7a5a3f"/><circle cx="250" cy="110" r="40" fill="#c9553f"/>',
    video: '<rect width="320" height="240" fill="#2b2f36"/><rect x="40" y="60" width="240" height="130" fill="#e9dfcf"/><path d="M30 60h260l-16 30H46z" fill="#c9553f"/><rect x="70" y="110" width="70" height="56" fill="#7fb0c9"/><rect x="180" y="110" width="52" height="80" fill="#6b4f3a"/>'
  };
  const BG = {terrace: '#9fc4dd', cup: '#3b2f25', people: '#cfd9c8', bake: '#f0e2c8', shop: '#a9c7dc', latte: '#f3e3cf', card: '#4a5d52', cover: '#b9cdbb', logo: '#0f1f1b', header: '#f3e3cf', video: '#2b2f36'};
  const pic = m => uri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 240"><rect width="320" height="240" fill="' + BG[m] + '"/>' + MOTIF[m] + '</svg>');
  // A first page for a PDF, drawn from its text.
  const page = (title, text) => uri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 320"><rect width="240" height="320" fill="#ffffff"/><text x="20" y="34" font-family="Helvetica,Arial,sans-serif" font-size="13" font-weight="700" fill="#1b1e23">' + esc(title) + '</text><rect x="20" y="44" width="200" height="1" fill="#c9ced6"/>' +
    text.split('\n').slice(0, 16).map((l, i) => '<text x="20" y="' + (66 + i * 15) + '" font-family="Helvetica,Arial,sans-serif" font-size="8.5" fill="#3a4049">' + esc(l) + '</text>').join('') + '</svg>');

  const KB = 1024, MB = 1048576;
  // Tickets: title in plain words, key, where it stands, its topic, and for done ones the day it was done.
  const T = {
    'DM-4': {key: 'DM-4', title: 'Summer terrace photos', status: 'done', done: '2026-10-06', topic: 'Marketing'},
    'DM-6': {key: 'DM-6', title: 'Price list 2027', status: 'done', done: '2026-10-12', topic: 'Prices'},
    'DM-9': {key: 'DM-9', title: 'Autumn newsletter', status: 'done', done: '2026-11-02', topic: 'Marketing'},
    'DM-12': {key: 'DM-12', title: 'Spring catalogue', status: 'review', topic: 'Marketing'},
    'DM-14': {key: 'DM-14', title: 'Opening hours on the website', status: 'done', done: '2026-10-26', topic: 'Website'},
    'DM-15': {key: 'DM-15', title: 'Allergen list', status: 'done', done: '2026-11-04', topic: 'Menus'},
    'DM-18': {key: 'DM-18', title: 'Newsletter ideas', status: 'working', topic: 'Marketing'},
    'DM-21': {key: 'DM-21', title: 'Check wholesale prices', status: 'working', topic: 'Prices'},
    'DM-23': {key: 'DM-23', title: 'Winter menu cards', status: 'review', topic: 'Menus'},
    'DM-25': {key: 'DM-25', title: 'Offer for Hotel Seeblick', status: 'working', topic: 'Sales'},
    'DM-27': {key: 'DM-27', title: 'Budget 2027', status: 'done', done: '2026-11-14', topic: 'Finance'}
  };

  const invoice114 = 'Invoice 2026-114\nCafé Demo GmbH, Seestrasse 12, 8002 Zürich\nTo: Bakery Müller AG, Bahnhofplatz 3, 8001 Zürich\nDate: 12 November 2026\n\n40 kg house blend coffee beans      CHF 880.00\n12 boxes oat cookies                CHF 264.00\nDelivery                            CHF 96.00\n\nTotal                               CHF 1,240.00\nPlease pay within 30 days. Thank you.';
  const invoice115 = 'Invoice 2026-115\nCafé Demo GmbH, Seestrasse 12, 8002 Zürich\nTo: Hotel Seeblick, Uferweg 8, 8038 Zürich\nDate: 16 November 2026\n\nBreakfast pastries, 2 weeks         CHF 1,960.00\nHouse blend coffee beans, 20 kg     CHF 440.00\n\nTotal                               CHF 2,400.00\nPlease pay within 30 days. Thank you.';
  const catalogue = 'Spring catalogue 2027\nFresh from our kitchen\n\nRhubarb tart, slice                 CHF 6.50\nLemon and poppy seed cake           CHF 5.80\nAsparagus quiche                    CHF 9.20\nElderflower lemonade, 3 dl          CHF 5.50\n\nNew: breakfast boxes for offices, from 6 people.\nOrder by phone or on our website.';
  const catalogueV3 = 'Spring catalogue 2027: draft 3\nFresh from our kitchen\n\nRhubarb tart, slice                 CHF 6.50\nLemon and poppy seed cake           CHF 5.80\nAsparagus quiche                    CHF 9.20\n\nOpen: photo for the cover, price of the breakfast box.';
  const catalogueV1 = 'Spring catalogue 2027: draft 1\nFresh from our kitchen\n\nRhubarb tart, slice                 CHF 6.00\nLemon cake                          CHF 5.50\n\nOpen: more dishes, all photos, the cover.';
  const catalogueV2 = 'Spring catalogue 2027: draft 2\nFresh from our kitchen\n\nRhubarb tart, slice                 CHF 6.50\nLemon and poppy seed cake           CHF 5.80\nAsparagus quiche                    CHF 9.00\n\nOpen: photo for the cover, elderflower lemonade.';
  const printOrder = 'Print order\nDruckerei am See, Zürich\n\n200 winter menu cards, A5, both sides\nPaper: 300 g, matt\nReady on 27 November\n\nTotal                               CHF 186.00';
  const priceList = 'Price list 2027 for business customers\nValid from 1 January 2027\n\nHouse blend coffee beans, 1 kg      CHF 22.00\nEspresso dark roast, 1 kg           CHF 24.50\nOat cookies, box of 24              CHF 22.00\nCroissants, tray of 30              CHF 39.00\n\nFree delivery in Zürich from CHF 300.';

  const files = [
    // ---- Workspace (top)
    {name: 'notes-team-meeting.md', folder: '', size: 2 * KB, changed: '2026-11-17T16:20', who: 'Severin',
      text: '# Team meeting, 17 November\n\n- Winter menu starts on 1 December, Ben prints the cards.\n- Anna sends the winter newsletter on 27 November.\n- New opening hours over the holidays: closed 24 to 26 December.\n- Hotel Seeblick wants a weekly pastry delivery; Ben writes the offer.'},
    {name: 'suppliers.json', folder: '', size: 1 * KB, changed: '2026-11-09T09:05', who: 'Ben',
      text: '{\n  "coffee": {"name": "Rösterei Albis", "delivery": "Tuesday", "contact": "orders@albis.example"},\n  "milk": {"name": "Hof Sonnenberg", "delivery": "daily"},\n  "flour": {"name": "Mühle Tiefenbrunnen", "delivery": "Monday"}\n}'},

    // ---- Marketing
    {name: 'shop-tour.mp4', folder: 'Marketing', size: 380 * MB, changed: '2026-11-05T14:02', who: 'Anna', poster: pic('video'), thumb: pic('video'), duration: '2:48'},
    {name: 'autumn-newsletter.md', folder: 'Marketing/Newsletter', size: 2 * KB, changed: '2026-11-02T10:32', who: 'Anna',
      text: '# Autumn at Café Demo\n\nDear friends, thank you for a wonderful summer on our terrace.\n\nThe pumpkin latte returns 3 Nov, together with our warm apple strudel.\nNew: oat milk from Hof Sonnenberg at no extra charge.\n\nSee you soon,\nAnna, Ben and Severin'},
    {name: 'winter-newsletter-draft.md', folder: 'Marketing/Newsletter', size: 3 * KB, changed: '2026-11-18T09:48', who: 'Anna',
      text: '# Winter at Café Demo (draft)\n\nDear friends, the first snow is here and so is our winter menu.\n\n- Hot chocolate with orange and cinnamon\n- Cheese fondue toast, every Friday\n- Gift cards for Christmas, at the counter and online\n\nWe are closed from 24 to 26 December.'},
    {name: 'subscribers.csv', folder: 'Marketing/Newsletter', size: 14 * KB, changed: '2026-11-14T11:10', who: 'Ben',
      text: 'name,email,since\nLea Keller,lea.keller@example.com,2025-03-02\nMarco Bianchi,marco@example.com,2025-06-18\nSofia Meier,sofia.meier@example.com,2026-01-09\nJonas Huber,jonas.huber@example.com,2026-04-21\nNina Frei,nina.frei@example.com,2026-09-30'},
    {name: 'newsletter-header.png', folder: 'Marketing/Newsletter', size: 420 * KB, changed: '2026-11-02T09:15', who: 'Anna', src: pic('header'), width: 1200, height: 400},
    {name: 'spring-catalogue-2027.pdf', folder: 'Marketing/Catalogue', size: 4.2 * MB, changed: '2026-11-16T15:40', who: 'Anna', pages: 2, thumb: page('Spring catalogue 2027', catalogue), text: catalogue},
    {name: 'catalogue-cover.png', folder: 'Marketing/Catalogue', size: 1.8 * MB, changed: '2026-11-13T17:22', who: 'Anna', src: pic('cover'), width: 2480, height: 3508},
    {name: 'catalogue-texts.md', folder: 'Marketing/Catalogue', size: 4 * KB, changed: '2026-11-12T13:05', who: 'Severin',
      text: '# Texts for the spring catalogue\n\n## Cover\nFresh from our kitchen: spring 2027.\n\n## Rhubarb tart\nBaked every morning with rhubarb from Hof Sonnenberg.\n\n## Breakfast boxes\nFor offices from 6 people. Order two days ahead.'},
    {name: 'terrace.jpg', folder: 'Marketing/Photos', size: 3.1 * MB, changed: '2026-11-03T12:10', who: 'Anna', src: pic('terrace'), width: 4032, height: 3024},
    {name: 'latte-art.jpg', folder: 'Marketing/Photos', size: 2.4 * MB, changed: '2026-11-03T12:12', who: 'Anna', src: pic('cup'), width: 4032, height: 3024},
    {name: 'team-2026.jpg', folder: 'Marketing/Photos', size: 3.6 * MB, changed: '2026-11-06T08:55', who: 'Severin', src: pic('people'), width: 4032, height: 3024},
    {name: 'croissants.jpg', folder: 'Marketing/Photos', size: 2.9 * MB, changed: '2026-11-10T07:40', who: 'Ben', src: pic('bake'), width: 4032, height: 3024},
    {name: 'shop-front.jpg', folder: 'Marketing/Photos', size: 3.3 * MB, changed: '2026-11-10T07:44', who: 'Ben', src: pic('shop'), width: 4032, height: 3024},
    {name: 'pumpkin-latte.jpg', folder: 'Marketing/Photos', size: 2.2 * MB, changed: '2026-11-02T08:30', who: 'Anna', src: pic('latte'), width: 3024, height: 4032},

    // ---- Sales
    {name: 'orders-november.csv', folder: 'Sales', size: 6 * KB, changed: '2026-11-18T08:15', who: 'Ben',
      text: 'date,customer,item,qty,total CHF\n2026-11-03,Bakery Müller AG,House blend 1 kg,40,880.00\n2026-11-04,Hotel Seeblick,Croissants tray of 30,12,468.00\n2026-11-06,Büro Limmat,Breakfast box,8,232.00\n2026-11-10,Bakery Müller AG,Oat cookies box of 24,12,264.00\n2026-11-12,Hotel Seeblick,House blend 1 kg,20,440.00\n2026-11-17,Kita Sonnenschein,Pumpkin soup 5 l,2,96.00'},
    {name: 'wholesale-prices.xlsx', folder: 'Sales', size: 28 * KB, changed: '2026-11-11T10:02', who: 'Ben',
      rows: [['Item', 'Unit', 'Price CHF', 'From 10 units'], ['House blend coffee beans', '1 kg', '22.00', '20.50'], ['Espresso dark roast', '1 kg', '24.50', '23.00'], ['Oat cookies', 'box of 24', '22.00', '20.00'], ['Croissants', 'tray of 30', '39.00', '36.00'], ['Breakfast box', 'per person', '29.00', '27.00']],
      text: 'Item Unit Price CHF From 10 units\nHouse blend coffee beans 1 kg 22.00 20.50\nEspresso dark roast 1 kg 24.50 23.00\nOat cookies box of 24 22.00 20.00\nCroissants tray of 30 39.00 36.00\nBreakfast box per person 29.00 27.00'},
    {name: 'customers.csv', folder: 'Sales', size: 3 * KB, changed: '2026-11-07T15:30', who: 'Ben',
      text: 'customer,contact,city,since\nBakery Müller AG,Peter Müller,Zürich,2024\nHotel Seeblick,Carla Rossi,Zürich,2025\nBüro Limmat,Tim Graf,Zürich,2026\nKita Sonnenschein,Eva Brunner,Kilchberg,2026'},
    {name: 'offer-hotel-seeblick.docx', folder: 'Sales', type: 'md', word: 'Word document', size: 34 * KB, changed: '2026-11-17T17:05', who: 'Ben',
      text: '# Offer for Hotel Seeblick\n\nDear Ms Rossi, thank you for your interest in a weekly delivery.\n\nWe offer breakfast pastries for 60 guests, delivered every morning by 6:30.\nPrice per week: CHF 980.00, with two weeks to try it out.\n\nKind regards, Ben'},
    {name: 'price-list-2027.pdf', folder: 'Sales', size: 310 * KB, changed: '2026-11-15T11:45', who: 'Severin', pages: 1, thumb: page('Price list 2027', priceList), text: priceList},

    // ---- Finance
    {name: 'invoice-2026-114.pdf', folder: 'Finance', size: 96 * KB, changed: '2026-11-12T09:20', who: 'Severin', pages: 1, thumb: page('Invoice 2026-114', invoice114), text: invoice114},
    {name: 'invoice-2026-115.pdf', folder: 'Finance', size: 94 * KB, changed: '2026-11-16T09:02', who: 'Severin', pages: 1, thumb: page('Invoice 2026-115', invoice115), text: invoice115},
    {name: 'budget-2027.xlsx', folder: 'Finance', size: 52 * KB, changed: '2026-11-13T14:18', who: 'Severin',
      rows: [['Area', 'Plan 2026 CHF', 'Plan 2027 CHF'], ['Coffee and milk', '48,000', '51,000'], ['Bakery goods', '36,000', '39,500'], ['Wages', '212,000', '221,000'], ['Rent', '54,000', '54,000'], ['Marketing', '9,000', '12,000']],
      text: 'Area Plan 2026 CHF Plan 2027 CHF\nCoffee and milk 48,000 51,000\nBakery goods 36,000 39,500\nWages 212,000 221,000\nRent 54,000 54,000\nMarketing 9,000 12,000'},
    {name: 'tax-notes.txt', folder: 'Finance', size: 1 * KB, changed: '2026-11-04T18:12', who: 'Severin',
      text: 'Tax notes 2026\nVAT return for the third quarter sent on 28 October.\nAsk the accountant about the new coffee machine (bought in September).\nKeep all receipts for the terrace repair.'},
    {name: 'till-export.bin', folder: 'Finance', size: 2.1 * MB, changed: '2026-11-01T22:00', who: 'Ben'},

    // ---- Menus
    {name: 'winter-menu.docx', folder: 'Menus', type: 'md', word: 'Word document', size: 41 * KB, changed: '2026-11-17T11:30', who: 'Ben',
      text: '# Winter menu\n\n## Warm drinks\nHot chocolate with orange and cinnamon, CHF 6.50\nChai latte, CHF 6.00\n\n## From the oven\nCheese fondue toast, CHF 12.50\nApple strudel with vanilla sauce, CHF 8.50\n\nAsk us about allergens: the list is at the counter.'},
    {name: 'allergens.md', folder: 'Menus', size: 2 * KB, changed: '2026-11-17T11:42', who: 'Ben',
      text: '# Allergens\n\n- Apple strudel: gluten, milk, eggs, nuts (almonds)\n- Cheese fondue toast: gluten, milk\n- Hot chocolate: milk (oat milk on request)\n- Oat cookies: gluten, may contain traces of nuts\n\nLast checked with the kitchen on 17 November.'},
    {name: 'menu-card-front.png', folder: 'Menus', size: 2.6 * MB, changed: '2026-11-17T12:05', who: 'Ben', src: pic('card'), width: 1748, height: 2480},
    {name: 'menu-card-back.png', folder: 'Menus', size: 2.3 * MB, changed: '2026-11-17T12:06', who: 'Ben', src: pic('card'), width: 1748, height: 2480},
    {name: 'menu-cards.zip', folder: 'Menus', size: 6.4 * MB, changed: '2026-11-17T12:20', who: 'Ben',
      files: [['menu-card-front.pdf', '3.1 MB'], ['menu-card-back.pdf', '2.8 MB'], ['fonts.txt', '1 KB'], ['print-notes.txt', '1 KB']], total: 4},

    // ---- Website (a small code project)
    {name: 'README.md', folder: 'Website', size: 1 * KB, changed: '2026-11-08T10:00', who: 'Severin',
      text: '# Café Demo website\n\nThe small website of the café: start page, menu and opening hours.\n\nTo change the opening hours, edit `src/opening-hours.js` and save.\nPictures live in `assets`.'},
    {name: 'opening-hours.js', folder: 'Website/src', size: 1 * KB, changed: '2026-11-17T16:45', who: 'Severin',
      text: '// Opening hours shown on the start page\nconst openingHours = {\n  weekdays: {open: "07:00", close: "18:30"},\n  saturday: {open: "08:00", close: "17:00"},\n  sunday: null, // closed\n  closedDays: ["2026-12-24", "2026-12-25", "2026-12-26"]\n};\nexport default openingHours;'},
    {name: 'index.html', folder: 'Website/src', size: 3 * KB, changed: '2026-11-08T10:12', who: 'Severin',
      html: '<body style="font-family:system-ui;margin:24px;color:#1b1e23"><h1>Café Demo</h1><p>Coffee, cake and a terrace by the lake.</p><h2>Opening hours</h2><p>Monday to Friday 7:00 to 18:30<br>Saturday 8:00 to 17:00<br>Sunday closed</p><p><a href="#">See the winter menu</a></p></body>',
      text: 'Café Demo\nCoffee, cake and a terrace by the lake.\nOpening hours\nMonday to Friday 7:00 to 18:30\nSaturday 8:00 to 17:00\nSunday closed\nSee the winter menu'},
    {name: 'style.css', folder: 'Website/src', size: 2 * KB, changed: '2026-11-08T10:14', who: 'Severin',
      text: '/* Colours of the café */\nbody { font-family: system-ui; color: #1b1e23; }\nh1 { color: #173c33; }\n.hours { border-top: 1px solid #ddd; padding-top: 16px; }\n.menu-link { font-weight: 600; }'},
    {name: 'logo.svg', folder: 'Website/assets', size: 4 * KB, changed: '2026-11-08T09:40', who: 'Anna', src: pic('logo'), width: 512, height: 512},
    {name: 'hero.jpg', folder: 'Website/assets', size: 1.4 * MB, changed: '2026-11-08T09:42', who: 'Anna', src: pic('terrace'), width: 2400, height: 1350},

    // ---- From tickets (made by helpers; each carries its ticket key and a title in plain words)
    // DM-12 Spring catalogue: three versions of one draft (shown as one stacked card)
    {name: 'catalogue-draft-v1.pdf', ticket: 'DM-12', title: 'Catalogue draft', version: 1, size: 3.1 * MB, changed: '2026-11-06T11:10', who: 'Helper', pages: 2, thumb: page('Spring catalogue 2027: draft 1', catalogueV1), text: catalogueV1},
    {name: 'catalogue-draft-v2.pdf', ticket: 'DM-12', title: 'Catalogue draft', version: 2, size: 3.5 * MB, changed: '2026-11-11T15:30', who: 'Helper', pages: 2, thumb: page('Spring catalogue 2027: draft 2', catalogueV2), text: catalogueV2},
    {name: 'catalogue-draft-v3.pdf', ticket: 'DM-12', title: 'Catalogue draft', version: 3, size: 3.8 * MB, changed: '2026-11-16T14:55', who: 'Helper', pages: 2, thumb: page('Spring catalogue 2027: draft 3', catalogueV3), text: catalogueV3},
    {name: 'cover-ideas-2026-11-12.png', ticket: 'DM-12', title: 'Cover ideas', size: 1.2 * MB, changed: '2026-11-12T10:05', who: 'Helper', src: pic('cover'), width: 2480, height: 3508},
    {name: 'catalogue-texts-checked-2026-11-14.md', ticket: 'DM-12', title: 'Catalogue texts: checked', size: 2 * KB, changed: '2026-11-14T09:20', who: 'Helper',
      text: '# Catalogue texts: checked\n\nAll prices match the price list 2027.\nTwo spelling fixes on page 2 (rhubarb, elderflower).\nThe breakfast box still has no price: Anna decides.'},
    // DM-18 Newsletter ideas
    {name: 'newsletter-ideas.md', ticket: 'DM-18', title: 'Ideas for the winter newsletter', size: 2 * KB, changed: '2026-11-18T09:30', who: 'Helper',
      text: '# Ideas for the winter newsletter\n\n1. "First snow, first fondue toast": lead with the Friday special.\n2. A short story about Hof Sonnenberg, where the milk comes from.\n3. Gift cards for Christmas, with a picture of the counter.\n4. Holiday opening hours at the end, in one line.'},
    {name: 'subject-lines-2026-11-18.md', ticket: 'DM-18', title: 'Subject lines to choose from', size: 1 * KB, changed: '2026-11-18T09:42', who: 'Helper',
      text: '# Subject lines to choose from\n\n- First snow, first fondue toast\n- Winter is here, and so is the hot chocolate\n- A warm hello from Café Demo'},
    {name: 'header-picture-2026-11-18.png', ticket: 'DM-18', title: 'Header picture', size: 380 * KB, changed: '2026-11-18T09:50', who: 'Helper', src: pic('latte'), width: 1200, height: 400},
    // DM-21 Check wholesale prices
    {name: 'price-check.csv', ticket: 'DM-21', title: 'Price check: numbers', size: 1 * KB, changed: '2026-11-18T10:20', who: 'Helper',
      text: 'item,our price CHF,market low,market high,note\nHouse blend 1 kg,22.00,19.50,26.00,in the middle\nEspresso dark roast 1 kg,24.50,21.00,27.50,in the middle\nOat cookies box of 24,22.00,23.00,28.00,cheaper than others\nCroissants tray of 30,39.00,33.00,38.00,a little high'},
    {name: 'summary.md', ticket: 'DM-21', title: 'Price check: summary', size: 1 * KB, changed: '2026-11-18T10:24', who: 'Helper',
      text: '# Wholesale prices: what the check found\n\nThree of four prices sit in the middle of the market.\nCroissants are CHF 1.00 above the highest price found; Bakery Müller AG pays less elsewhere.\nOat cookies could go up by CHF 1.00 without standing out.'},
    {name: 'sources-2026-11-18.md', ticket: 'DM-21', title: 'Price check: sources', size: 1 * KB, changed: '2026-11-18T10:26', who: 'Helper',
      text: '# Where the numbers come from\n\n- Price lists of three bakeries in Zürich, read on 18 November\n- Two coffee roasters with public wholesale prices\n- Our own price list 2027'},
    // DM-23 Winter menu cards
    {name: 'menu-card-front-2026-11-15.png', ticket: 'DM-23', title: 'Menu card: front', size: 2.2 * MB, changed: '2026-11-15T16:10', who: 'Helper', src: pic('card'), width: 1748, height: 2480},
    {name: 'menu-card-back-2026-11-15.png', ticket: 'DM-23', title: 'Menu card: back', size: 2.0 * MB, changed: '2026-11-15T16:12', who: 'Helper', src: pic('bake'), width: 1748, height: 2480},
    {name: 'winter-menu-texts-2026-11-15.md', ticket: 'DM-23', title: 'Winter menu: texts for the card', size: 2 * KB, changed: '2026-11-15T15:40', who: 'Helper',
      text: '# Winter menu: texts for the card\n\nHot chocolate with orange and cinnamon   CHF 6.50\nCheese fondue toast, Fridays            CHF 12.00\nChestnut cake, slice                    CHF 7.00\n\nAllergens are marked with small letters, see the allergen list.'},
    {name: 'print-order-2026-11-17.pdf', ticket: 'DM-23', title: 'Print order', size: 180 * KB, changed: '2026-11-17T12:30', who: 'Helper', pages: 1, thumb: page('Print order', printOrder), text: printOrder},
    // DM-25 Offer for Hotel Seeblick
    {name: 'offer-draft-2026-11-18.md', ticket: 'DM-25', title: 'Offer for Hotel Seeblick: draft', size: 2 * KB, changed: '2026-11-18T08:55', who: 'Helper',
      text: '# Offer for Hotel Seeblick: draft\n\nWeekly pastry delivery, every Monday before 7:00.\n60 croissants, 40 cinnamon buns, 2 chestnut cakes.\nPrice per week: CHF 490.00, delivery included.\nOpen: does the hotel want a second delivery on Fridays?'},
    {name: 'delivery-plan-2026-11-18.csv', ticket: 'DM-25', title: 'Delivery plan', size: 1 * KB, changed: '2026-11-18T09:05', who: 'Helper',
      text: 'day,what,pieces,ready by\nMonday,Croissants,60,06:30\nMonday,Cinnamon buns,40,06:30\nMonday,Chestnut cake,2,06:30\nFriday,Croissants (if wanted),40,06:30'},
    // DM-27 Budget 2027 (done)
    {name: 'budget-overview-2026-11-13.csv', ticket: 'DM-27', title: 'Budget 2027: overview', size: 1 * KB, changed: '2026-11-13T14:00', who: 'Helper',
      text: 'part,2026 CHF,2027 CHF\nCoffee and milk,48000,51000\nFlour and baking,22000,23500\nRent,36000,36000\nWages,184000,192000\nMarketing,6000,9000'},
    {name: 'budget-notes-2026-11-14.md', ticket: 'DM-27', title: 'Budget 2027: what changes', size: 1 * KB, changed: '2026-11-14T10:15', who: 'Helper',
      text: '# Budget 2027: what changes\n\nMarketing goes up by CHF 3,000 for the spring catalogue.\nWages rise with the new part-time baker from March.\nRent stays the same until 2028.'},
    // DM-15 Allergen list (done; two files with the same title get their time beside them)
    {name: 'allergen-list-2026-11-03.md', ticket: 'DM-15', title: 'Allergen list', size: 2 * KB, changed: '2026-11-03T11:20', who: 'Helper',
      text: '# Allergen list\n\n- Chestnut cake: nuts, eggs, milk\n- Cinnamon bun: gluten, milk, eggs\n- Fondue toast: gluten, milk\n- Oat cookies: gluten (oats)'},
    {name: 'allergen-card-2026-11-03.png', ticket: 'DM-15', title: 'Allergen card', size: 640 * KB, changed: '2026-11-03T14:02', who: 'Helper', src: pic('card'), width: 1240, height: 1748},
    {name: 'allergen-card-2026-11-04.png', ticket: 'DM-15', title: 'Allergen card', size: 655 * KB, changed: '2026-11-04T09:15', who: 'Helper', src: pic('card'), width: 1240, height: 1748},
    // DM-9 Autumn newsletter (done; made in October, the report came in November)
    {name: 'autumn-newsletter-draft-2026-10-28.md', ticket: 'DM-9', title: 'Autumn newsletter: draft', size: 2 * KB, changed: '2026-10-28T15:10', who: 'Helper',
      text: '# Autumn newsletter: draft\n\nDear friends, thank you for a wonderful summer on our terrace.\nThe pumpkin latte returns 3 Nov.\nNew: oat milk at no extra charge.'},
    {name: 'newsletter-header-2026-10-29.png', ticket: 'DM-9', title: 'Newsletter header', size: 410 * KB, changed: '2026-10-29T09:30', who: 'Helper', src: pic('header'), width: 1200, height: 400},
    {name: 'send-report-2026-11-02.md', ticket: 'DM-9', title: 'Autumn newsletter: who opened it', size: 1 * KB, changed: '2026-11-02T17:00', who: 'Helper',
      text: '# Autumn newsletter: who opened it\n\nSent to 412 people on 2 November at 10:30.\n236 opened it, 41 clicked on the pumpkin latte picture.\n3 people left the list.'},
    // DM-14 Opening hours on the website (done in October)
    {name: 'opening-hours-change-2026-10-26.md', ticket: 'DM-14', title: 'Opening hours: what was changed', size: 1 * KB, changed: '2026-10-26T13:45', who: 'Helper',
      text: '# Opening hours: what was changed\n\nSaturday now closes at 17:00 instead of 16:00.\nThe holiday days 24 to 26 December are marked as closed.\nThe start page shows the new hours.'},
    {name: 'start-page-after-2026-10-26.png', ticket: 'DM-14', title: 'Start page with the new hours', size: 720 * KB, changed: '2026-10-26T13:50', who: 'Helper', src: pic('shop'), width: 1440, height: 900},
    // DM-6 Price list 2027 (done long ago)
    {name: 'price-list-draft-2026-10-09.pdf', ticket: 'DM-6', title: 'Price list 2027: draft', size: 240 * KB, changed: '2026-10-09T10:00', who: 'Helper', pages: 1, thumb: page('Price list 2027', priceList), text: priceList},
    {name: 'price-changes-2026-10-12.csv', ticket: 'DM-6', title: 'Price changes from 2026 to 2027', size: 1 * KB, changed: '2026-10-12T09:10', who: 'Helper',
      text: 'item,2026 CHF,2027 CHF\nHouse blend 1 kg,21.00,22.00\nEspresso dark roast 1 kg,23.50,24.50\nOat cookies box of 24,21.00,22.00\nCroissants tray of 30,37.00,39.00'},
    // DM-4 Summer terrace photos (done long ago)
    {name: 'terrace-evening-2026-10-05.jpg', ticket: 'DM-4', title: 'Terrace in the evening', size: 2.8 * MB, changed: '2026-10-05T18:20', who: 'Helper', src: pic('terrace'), width: 3000, height: 2000},
    {name: 'team-on-terrace-2026-10-05.jpg', ticket: 'DM-4', title: 'Team on the terrace', size: 3.1 * MB, changed: '2026-10-05T18:32', who: 'Helper', src: pic('people'), width: 3000, height: 2000},
    {name: 'cake-table-2026-10-05.jpg', ticket: 'DM-4', title: 'Cake table', size: 2.4 * MB, changed: '2026-10-05T18:40', who: 'Helper', src: pic('bake'), width: 3000, height: 2000},
    {name: 'photo-notes-2026-10-06.md', ticket: 'DM-4', title: 'Photos: which ones to use', size: 1 * KB, changed: '2026-10-06T09:00', who: 'Helper',
      text: '# Photos: which ones to use\n\nThe evening terrace picture works best for the catalogue cover.\nThe team picture needs Anna’s yes before it goes online.'}
  ];
  // Titles for your own files: the first heading of a document, else a plain reading of the name
  const TITLES = {'suppliers.json': 'Suppliers', 'subscribers.csv': 'Newsletter subscribers', 'orders-november.csv': 'Orders in November', 'offer-hotel-seeblick.docx': 'Offer for Hotel Seeblick',
    'invoice-2026-114.pdf': 'Invoice 2026-114: Bakery Müller AG', 'invoice-2026-115.pdf': 'Invoice 2026-115: Hotel Seeblick', 'menu-cards.zip': 'Menu cards for the printer', 'index.html': 'Start page',
    'style.css': 'Colours of the café', 'hero.jpg': 'Start page picture', 'README.md': 'About the website', 'menu-card-front.png': 'Menu card: front', 'menu-card-back.png': 'Menu card: back'};
  const plain = n => { const s = n.replace(/\.[a-z0-9]+$/i, '').replace(/[-_]+/g, ' '); return s[0].toUpperCase() + s.slice(1); };
  files.forEach(f => { if (!f.ticket) f.title = TITLES[f.name] || (/^# /.test(f.text || '') ? f.text.split('\n')[0].slice(2) : plain(f.name)); else f.folder = ''; });
  files.forEach((f, i) => { f.id = 'f' + i; f.size = Math.round(f.size); });

  window.FILES_DATA = {
    now: '2026-11-18T10:40',
    workspace: 'Demo',
    lastLooked: '2026-11-17T18:00',   // "New for you" = changed since then
    files, tickets: T,
    topics: ['Marketing', 'Prices', 'Menus', 'Sales', 'Finance', 'Website'],
    starred: ['winter-menu.docx', 'orders-november.csv', 'spring-catalogue-2027.pdf'],
    building: {read: 3412, total: 8950}
  };
})();
