// POST /api/subscribe {email, team, name}: sends a confirm-your-email message. Nothing is stored until it's clicked.
import { SITE, sign, sendMail, validEmail, validTeam, esc } from '../lib/rr.mjs';

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });
  let b = {};
  try { b = await req.json(); } catch (e) { return Response.json({ ok: false, error: 'Bad request' }, { status: 400 }); }
  if (b.website) return Response.json({ ok: true });                       // honeypot: bots fill every field
  const email = String(b.email || '').trim().toLowerCase(), team = String(b.team || '');
  if (!validEmail(email)) return Response.json({ ok: false, error: 'That email address doesn\'t look right.' }, { status: 400 });
  if (!validTeam(team)) return Response.json({ ok: false, error: 'Pick a team first.' }, { status: 400 });
  const name = String(b.name || 'your team').slice(0, 80);
  const link = `${SITE}/api/confirm?e=${encodeURIComponent(email)}&t=${encodeURIComponent(team)}&s=${sign(email, team, 'confirm')}&n=${encodeURIComponent(name)}`;
  const html = `<div style="font:16px/1.55 system-ui,sans-serif;color:#14202a;max-width:520px">
    <p style="font:800 22px Impact,sans-serif;margin:0 0 12px">RINK<span style="color:#c8203a">RANK</span></p>
    <p>Tap below to get a short email every Monday morning about <b>${esc(name)}</b>: last week's results, this week's games and where they stand in their flight.</p>
    <p><a href="${link}" style="display:inline-block;background:#c8203a;color:#fff;font-weight:700;padding:12px 20px;border-radius:999px;text-decoration:none">Yes, send me the Monday email</a></p>
    <p style="color:#5b6b78;font-size:13px">If you didn't ask for this, ignore this email and nothing will happen. RinkRank is a free, independent site for PCAHA minor hockey families.</p></div>`;
  const r = await sendMail(email, `Confirm your RinkRank Monday email for ${name}`, html);
  if (!r.ok) { console.log('brevo send failed', r.status, JSON.stringify(r.data)); return Response.json({ ok: false, error: 'Couldn\'t send right now. Please try again later.' }, { status: 502 }); }
  return Response.json({ ok: true });
};
export const config = { path: '/api/subscribe' };
