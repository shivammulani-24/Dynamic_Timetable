/**
 * End-to-end smoke test: drives the real app (web target of the same Expo codebase) against the
 * real backend. Requires: API on :8000 with demo seed, worker running, web build served on :8081.
 *   node e2e/smoke.e2e.mjs [baseUrl] [screenshotDir]
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.argv[2] ?? 'http://localhost:8081';
const SHOTS = process.argv[3] ?? './e2e-screens';
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
  try { await page.getByText(text, { exact }).first().waitFor({ timeout }); return true; } catch { return false; }
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

// ---------------------------------------------------------------- student flow
await login('alice@demo.college.edu');
check('student dashboard loads', await visible('Quick actions'));
check('dashboard shows NEXT card', await visible('NEXT'));
await page.waitForTimeout(1200);
await shot('03-student-home');

await page.getByText('Timetable', { exact: true }).last().click();
check('weekly timetable tab', await visible('My classes', 3000) || await visible('Today'));
await page.waitForTimeout(1500);
await shot('04-student-week');

await page.getByText('Ask', { exact: true }).last().click();
await page.getByRole('textbox', { name: 'Question' }).fill('Find all DBMS classes');
await page.keyboard.press('Enter');
check('NL search returns DBMS results', await visible('Database Management Systems'));
await page.waitForTimeout(800);
await shot('05-search-dbms');

await page.getByRole('textbox', { name: 'Question' }).fill('Am I free at 2?');
await page.keyboard.press('Enter');
check('ambiguous AM/PM asks clarification', await visible('Did you mean'));
await shot('06-clarify-ampm');
await page.getByRole('button', { name: '2:00 PM' }).last().click();
check('clarification then asks date', await visible('Which date do you mean'));
await page.getByRole('button', { name: /Today/ }).last().click();
check('clarified answer returned', await visible(/Nothing scheduled|Scheduled|Cannot confirm/));
await shot('07-clarify-answered');

await page.getByRole('textbox', { name: 'Question' }).fill('Compare my personal and college timetable');
await page.keyboard.press('Enter');
check('cross-domain compare rejected', await visible('Not supported'));
await shot('08-cross-domain');

// Personal view must never fall back to college data.
await page.getByRole('tab', { name: 'Personal' }).first().click();
await page.getByRole('textbox', { name: 'Question' }).fill('What is my next class?');
await page.keyboard.press('Enter');
await page.waitForTimeout(1500);
check('personal search uses personal timetable', await visible('My semester plan', 8000) || await visible('next class', 8000));
await shot('09-personal-search');

await page.getByText('Archives', { exact: true }).last().click();
check('personal archive lists own upload', await visible('My semester plan'));
await shot('10-personal-archives');

// ---------------------------------------------------------------- admin flow
await page.getByText('Profile', { exact: true }).last().click();
page.once('dialog', (d) => d.accept()); // web uses window.confirm (lib/dialogs.ts)
await page.getByRole('button', { name: 'Sign out' }).click();
check('sign-out returns to welcome without reload', await visible('Your timetable,'));
await login('admin@demo.college.edu');
check('admin dashboard shows system stats', await visible('Active users'));
await shot('11-admin-home');
await page.getByText('Admin', { exact: true }).last().click();
check('admin hub', await visible('Users & roles'));
await shot('12-admin-hub');
await page.getByText('Rooms', { exact: true }).first().click();
check('rooms master data', await visible('702-B'));
await shot('13-admin-rooms');

// ---------------------------------------------------------------- admin upload through the UI
const FIXTURE = process.env.UPLOAD_FIXTURE;
if (FIXTURE) {
  await page.goBack(); // back to the Admin hub (in-app navigation keeps the in-memory web session)
  await page.getByText('Upload official timetable').click();
  check('upload screen (official)', await visible('Official college timetable'));
  const chooser = page.waitForEvent('filechooser');
  await page.getByText('Choose a timetable file').click();
  await (await chooser).setFiles(FIXTURE);
  await page.getByRole('textbox', { name: 'Title' }).fill('E2E upload (synthetic)');
  await shot('14-upload-form');
  await page.getByRole('button', { name: 'Upload & process' }).click();
  check('upload accepted', await visible('Uploaded & stored privately'));
  check('worker finished processing', await visible('Validation summary', 60000, true));
  await shot('15-upload-processed');
  await page.getByRole('button', { name: 'Open timetable' }).click();
  check('timetable detail shows extraction summary', await visible('Extraction summary'));
  check('activation action offered to admin', await visible('Activate as official timetable'));
  await shot('16-timetable-detail');
}

console.log('\nAPI calls observed:', [...new Set(apiCalls)].slice(0, 40).join('\n  '));
console.log('\nPage errors:', errors.length ? errors.join('\n') : 'none');
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
