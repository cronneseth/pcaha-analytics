// Shared bits for the Monday email sign-up: signed links and the Brevo API.
// Env (set in Netlify): BREVO_API_KEY, RR_SECRET. Optional: RR_FROM (default no-reply@rinkrank.net).
import { createHmac, timingSafeEqual } from 'node:crypto';

export const SITE = (process.env.URL || 'https://rinkrank.net').replace(/\/$/, '');
export const FROM = { name: 'RinkRank', email: process.env.RR_FROM || 'no-reply@rinkrank.net' };
const API = 'https://api.brevo.com/v3';

// Same recipe as scripts/weekly_email.py: HMAC-SHA256 of "email|team|action", base64url, 32 chars.
export function sign(email, team, action) {
  return createHmac('sha256', process.env.RR_SECRET || '').update(`${email.toLowerCase()}|${team}|${action}`).digest('base64url').slice(0, 32);
}
export function verify(email, team, action, sig) {
  const a = Buffer.from(sign(email, team, action)), b = Buffer.from(String(sig || ''));
  return a.length === b.length && timingSafeEqual(a, b);
}
export const validEmail = e => typeof e === 'string' && e.length <= 254 && /^[^\s@<>"]+@[^\s@<>"]+\.[a-z]{2,}$/i.test(e);
export const validTeam = t => typeof t === 'string' && /^u\d{1,2}:\d{1,9}$/.test(t);
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export async function brevo(path, method = 'GET', body) {
  const r = await fetch(API + path, {
    method,
    headers: { 'api-key': process.env.BREVO_API_KEY || '', accept: 'application/json', 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
  return { ok: r.ok, status: r.status, data };
}

export async function sendMail(to, subject, html, headers) {
  return brevo('/smtp/email', 'POST', { sender: FROM, to: [{ email: to }], subject, htmlContent: html, headers });
}

// A contact's followed teams live in one text attribute, TEAMS: "u13:178148,u15:123".
export async function getTeams(email) {
  const r = await brevo(`/contacts/${encodeURIComponent(email)}`);
  if (!r.ok) return null;
  return String((r.data.attributes || {}).TEAMS || '').split(',').filter(validTeam);
}
export async function setTeams(email, teams) {
  await brevo('/contacts/attributes/normal/TEAMS', 'POST', { type: 'text' });   // first time only; errors after
  const r = await brevo('/contacts', 'POST', { email, attributes: { TEAMS: teams.join(',') }, updateEnabled: true, emailBlacklisted: false });
  return r.ok || r.status === 204;
}

export function page(title, body) {
  return new Response(`<!doctype html><html lang="en-CA"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} | RinkRank</title><meta name="robots" content="noindex">
<style>body{margin:0;background:#f2f5f7;color:#14202a;font:18px/1.55 system-ui,sans-serif}.w{max-width:560px;margin:60px auto;padding:0 18px}
.c{background:#fff;border:1px solid #d8e0e6;border-radius:14px;padding:22px 24px}h1{font:800 30px/1.1 Impact,system-ui,sans-serif;text-transform:uppercase;margin:0 0 10px}
a.b{display:inline-block;background:#c8203a;color:#fff;font-weight:700;padding:11px 18px;border-radius:999px;text-decoration:none;margin-top:8px}</style></head>
<body><div class="w"><p style="font:800 26px Impact,sans-serif;margin:0 0 14px">RINK<span style="color:#c8203a">RANK</span></p><div class="c"><h1>${esc(title)}</h1>${body}</div></div></body></html>`,
    { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
}
