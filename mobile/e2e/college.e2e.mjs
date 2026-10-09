/**
 * End-to-end test on the college's REAL timetable: drives the app (web target of the same Expo
 * codebase) against the real backend seeded with `scripts/dev.sh seed-college`.
 * Requires: API on :8000, worker running, web build served on :8081.
 *   node e2e/college.e2e.mjs [baseUrl] [screenshotDir]
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.argv[2] ?? 'http://localhost:8081';
const SHOTS = process.argv[3] ?? './e2e-college-screens';
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
function check(name, ok, info = '') {
  results.push({ name, ok, info });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${info ? ` — ${info}` : ''}`);
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
const apiCalls = [];
page.on('response', (r) => { if (r.url().includes('/api/v1/')) apiCalls.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
const shot = (n) => page.screenshot({ path: path.join(SHOTS, `${n}.png`) });
const visible = async (text, timeout = 15000, exact = false) => {
  try { await page.getByText(text, { exact }).filter({ visible: true }).first().waitFor({ timeout }); return true; } catch { return false; }
};

async function login(email) {
  await page.goto(BASE);
  check('welcome screen renders', await visible('Your timetable,'));
  await shot('01-welcome');
  await page.getByRole('button', { name: 'Sign in' }).first().click();
  await page.getByRole('textbox', { name: 'College email' }).fill(email);
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill('Demo@12345');
  await shot('02-login');
  await page.getByRole('button', { name: 'Sign in' }).last().click();
}

// Web keeps earlier tab screens mounted underneath; click the copy that is actually on top.
async function clickTop(locator) {
  for (const el of await locator.all()) {
    const box = await el.boundingBox();
    if (!box) continue;
    const x = box.x + box.width / 2, y = box.y + box.height / 2;
    const onTop = await el.evaluate((node, [px, py]) => node.contains(document.elementFromPoint(px, py)), [x, y]);
    if (onTop) { await page.mouse.click(x, y); return true; }
  }
  return false;
}

async function signOut() {
  await page.getByText('Profile', { exact: true }).last().click();
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: 'Sign out' }).click();
  await visible('Your timetable,');
}

async function openDay(short) {
  await page.getByText('Timetable', { exact: true }).last().click();
  await page.waitForTimeout(800);
  await clickTop(page.getByText(short, { exact: true }));
  await page.waitForTimeout(1200);
}

// ---------------------------------------------------------------- SE-A1 student
await login('student.se.a1@demo.college.edu');
check('student dashboard loads', await visible('Quick actions'));
await shot('01-se-a1-home');

await openDay('Mon');
check('Monday shows LLC as a course', await visible('Co Curricular Course'));
check('printed code shown under the name', await visible('LLC', 5000, true));
check('noon-row class shown normally (DS 12:15)', await visible('12:15 PM', 5000));
check('no "Unverified" tag on Monday', !(await visible('Unverified', 1500, true)));
await shot('02-se-a1-monday');
check('LLC card tappable', await clickTop(page.getByText('Co Curricular Course')));
check('class details open', await visible('When', 8000, true));
check('no professor row for LLC', !(await visible('Professor', 1500, true)));
check('no room row for LLC', !(await visible('Scheduled room', 1500, true)));
await shot('03-llc-details');
await page.goBack();

await openDay('Wed');
check('own lab group lab shown (DS Lab A1)', await visible('Data Structures (Lab)'));
await shot('04-se-a1-wednesday');

await page.getByText('Ask', { exact: true }).last().click();
await page.getByRole('textbox', { name: 'Question' }).fill('Do I have classes after lunch on Tuesday?');
await page.keyboard.press('Enter');
check('after-lunch answer uses SE lunch (2:15 PM)', await visible('Computer Organization', 15000));
await shot('05-after-lunch');
await signOut();

// ---------------------------------------------------------------- BE student (combined BE A–D page)
await login('student.be.c@demo.college.edu');
check('BE student dashboard loads', await visible('Quick actions'));
await openDay('Tue');
check('BE-C sees the combined BE page', await visible('Time Series & Data Analysis'));
await shot('06-be-c-tuesday');
await signOut();

// ---------------------------------------------------------------- HOD: conflicts
await login('snd@demo.college.edu');
check('HOD dashboard loads', await visible('Quick actions'));
check('conflicts banner shows exactly 2', await visible('2 possible schedule conflicts'));
await shot('07-hod-home');
await clickTop(page.getByText('Review conflicts'));
check('professor clash from the PDF listed', await visible('Prof. Sushama Pande'));
check('room clash from the PDF listed', await visible('603-2'));
await shot('08-conflicts');

console.log('\nPage errors:', errors.length ? errors.join('\n') : 'none');
const bad = [...new Set(apiCalls)].filter((c) => /^5/.test(c));
check('no server errors', bad.length === 0, bad.join(', '));
check('no page errors', errors.length === 0);
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
