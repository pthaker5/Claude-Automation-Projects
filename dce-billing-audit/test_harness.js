// test_harness.js — regression test for the DC&E billing audit dashboard
// Usage: node test_harness.js [path/to/billing_audit_vNN.html]
// Requires: npm i xlsx papaparse
// Place real SSRS exports in ./test_data/ (filenames matched by keyword below).
//
// What it does: extracts the live engine from the HTML (no copy/paste drift),
// shims the one DOM call, parses the exports the same way the app does,
// decodes the embedded rate blob, runs engine(), prints category counts.
// Diff the counts against BASELINE after every change and explain every delta.

const XLSX = require('xlsx');
const Papa = require('papaparse');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const HTML = process.argv[2] || fs.readdirSync('.').filter(f => /^billing_audit_v\d+\.html$/.test(f)).sort().pop();
if (!HTML) { console.error('No billing_audit_v*.html found'); process.exit(1); }
const DATA = './test_data';

// v32 baseline, week of 2026-05-18 exports, verified by running the actual
// extracted engine (this harness) on 2026-05-29. Update when test_data changes.
const BASELINE = {
  total: 979,
  '$0 + Billing Link': 20, 'No Charges': 0, 'Missing Charges': 477,
  'Sampling Overbill': 0, 'Handling on SO': 0, 'Missing Supply': 91,
  'BO Trailer-Trailer': 41, 'Missing Terminal Fee': 78,
  'Railcar Switch (Weekend Miss)': 2, 'Missing Switch Fee': 12,
  'Repack + Handling Out': 0, 'Packaging Audit': 9, 'Sample Minimum Rate': 18,
  'Boxing Material Audit': 83, 'Qty Mismatch (SS/HF/PLT)': 0,
  'Bag Qty Not Updated': 10, 'Railcar Storage': 36, 'Accuracy — Large Charge': 0,
  'Railcar Min Packaging': 9, 'Fee Qty > 1': 0, 'Near-Zero Loose Loading': 8,
  'Rate Mismatch': 66, 'Not in Rate Table': 7,
  '⚠ Manual — Review': 11, '✓ Manual — Verified': 1,
};

// ---- extract engine from the HTML ----
const src = fs.readFileSync(HTML, 'utf8');
const blocks = [...src.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const app = blocks.reduce((a, b) => (b.length > a.length ? b : a), '');
const rateM = app.match(/_EMBEDDED_RATES_B64\s*=\s*'([A-Za-z0-9+/=]+)'/);
if (!rateM) { console.error('Rate blob not found'); process.exit(1); }
const rateCsv = Buffer.from(rateM[1], 'base64').toString('binary');

// run the app script in a sandbox with shims; we only need its pure functions
const stubEl = () => ({ value: '', innerHTML: '', textContent: '', style: {},
  classList: { add(){}, remove(){}, toggle(){}, contains: () => false },
  addEventListener(){}, appendChild(){}, setAttribute(){}, dataset: {} });
const sandbox = {
  console, atob: s => Buffer.from(s, 'base64').toString('binary'),
  Q: stubEl,
  document: { getElementById: stubEl, querySelector: stubEl, querySelectorAll: () => [], addEventListener(){}, createElement: stubEl, body: stubEl() },
  window: {}, FileReader: function(){}, Papa, setTimeout: () => {}, fetch: () => Promise.reject(),
};
sandbox.window = sandbox;
vm.createContext(sandbox);
// Eval ONLY the slice from the first config constant through the end of engine().
// Evaluating the whole app would run UI init (settings toggles read from stubbed
// DOM elements) and silently change check behavior vs the real browser defaults.
const start = app.indexOf('var CPI_TOL');
const engStart = app.indexOf('function engine(');
if (start < 0 || engStart < 0) { console.error('Could not locate CPI_TOL / engine()'); process.exit(1); }
let i = app.indexOf('{', engStart), depth = 1;
while (depth > 0 && i < app.length - 1) { i++; if (app[i] === '{') depth++; else if (app[i] === '}') depth--; }
const slice = app.slice(start, i + 1);
try { vm.runInContext(slice, sandbox); } catch (e) { console.error('Slice eval failed:', e.message); process.exit(1); }
if (typeof sandbox.engine !== 'function') { console.error('engine() not found after eval:', ); process.exit(1); }

// ---- parsers mirroring the app ----
const wb = p => XLSX.read(fs.readFileSync(p), { type: 'buffer', cellDates: true });
const px = p => XLSX.utils.sheet_to_json(wb(p).Sheets[wb(p).SheetNames[0]], { defval: null });
function pxAllSheets(p) {
  const w = wb(p);
  const hdr = XLSX.utils.sheet_to_json(w.Sheets[w.SheetNames[0]], { header: 1, defval: null })[0] || [];
  let out = [];
  w.SheetNames.forEach(sn => {
    XLSX.utils.sheet_to_json(w.Sheets[sn], { header: 1, cellDates: true, defval: null }).forEach(row => {
      if (row[0]) return;
      const o = {}; hdr.forEach((c, i) => { if (c != null) o[c] = row[i] !== undefined ? row[i] : null; });
      out.push(o);
    });
  });
  return out.length ? out : px(p);
}
function pxRange3(p, key) {
  const w = wb(p), ws = w.Sheets[w.SheetNames[0]];
  let std = XLSX.utils.sheet_to_json(ws, { defval: null });
  if (std.length && std[0][key]) return std.filter(x => x[key] != null);
  return XLSX.utils.sheet_to_json(ws, { defval: null, range: 3 }).filter(x => x[key] != null);
}
function pxBxm(p) {
  const w = wb(p), ws = w.Sheets[w.SheetNames[0]];
  return XLSX.utils.sheet_to_json(ws, { defval: null, range: 1 })
    .filter(x => x['Order Num'] != null)
    .map(x => ({
      customer_code: String(x['customer code'] || '').trim(),
      customer_name: String(x['customer name'] || '').trim(),
      invoice_number: String(x['invoice number'] || '').trim(),
      closed_date: x['closed date'],
      description: String(x['description'] || '').trim(),
      order_num: String(x['Order Num'] || '').trim(),
      qty: x['Qty'],
      desc2: String(x['Description 2'] || '').trim(),
      charge_amount: parseFloat(x['charge amount']) || 0,
      location: String(x['location'] || '').trim(),
      wh_id: String(x['wh id'] || '').trim(),
      src_vessel: String(x['source vessel'] || '').trim(),
      dest_vessel: String(x['dest vessel'] || '').trim(),
    }));
}
const find = kw => {
  const f = fs.readdirSync(DATA).find(f => f.toLowerCase().includes(kw));
  return f ? path.join(DATA, f) : null;
};

// ---- load (keyword routing mirrors the app's drop router, lost-before-revenue) ----
const paths = {
  lost: find('lost'), inv: find('chargeback') || find('revenue_by'),
  nc: find('no_charges'), rc: find('railcar'), pkg: find('packaging'), bxm: find('boxing'),
};
for (const [k, v] of Object.entries(paths)) if (!v && (k === 'inv' || k === 'lost')) { console.error('Missing required test file:', k); process.exit(1); }

const inv = px(paths.inv);
const lost = pxAllSheets(paths.lost).filter(r => r['WH ID'] != null);
const nc = paths.nc ? px(paths.nc) : [];
const rc = paths.rc ? pxRange3(paths.rc, 'WH ID') : [];
const pkg = paths.pkg ? pxRange3(paths.pkg, 'Warehouse') : [];
const bxm = paths.bxm ? pxBxm(paths.bxm) : [];
const rr = Papa.parse(rateCsv, { header: true, skipEmptyLines: true }).data;

console.log(`engine source: ${HTML}`);
console.log(`rows — inv:${inv.length} lost:${lost.length} nc:${nc.length} rc:${rc.length} pkg:${pkg.length} bxm:${bxm.length} rates:${rr.length}\n`);

// ---- run ----
const R = sandbox.engine(inv, lost, rr, nc, rc, pkg, null, null, bxm);

const byCat = {};
R.items.forEach(i => { byCat[i.cat] = (byCat[i.cat] || 0) + 1; });

let drift = 0;
console.log('CATEGORY'.padEnd(34) + 'COUNT'.padStart(6) + 'BASE'.padStart(7) + '  DELTA');
const cats = new Set([...Object.keys(byCat), ...Object.keys(BASELINE).filter(k => k !== 'total')]);
[...cats].sort().forEach(c => {
  const n = byCat[c] || 0, b = BASELINE[c];
  const d = b === undefined ? '(new)' : n === b ? '' : (n > b ? '+' : '') + (n - b);
  if (d && d !== '(new)') drift++;
  console.log(c.padEnd(34) + String(n).padStart(6) + String(b === undefined ? '-' : b).padStart(7) + '  ' + d);
});
console.log('\nTOTAL'.padEnd(34) + String(R.items.length).padStart(7) + String(BASELINE.total).padStart(7));

const bad = R.items.filter(i => /NaN|undefined/.test(JSON.stringify(i.det || {}))).length;
console.log('items with NaN/undefined in detail:', bad);
console.log(drift || R.items.length !== BASELINE.total ? '\n!! DRIFT vs baseline — explain every delta before shipping' : '\nOK — matches baseline');
process.exit(bad > 0 ? 1 : 0);
