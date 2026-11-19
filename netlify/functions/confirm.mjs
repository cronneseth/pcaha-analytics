// GET /api/confirm?e&t&s: the link in the confirmation email. Adds the team to the contact in Brevo.
import { verify, getTeams, setTeams, page, validTeam, esc, sendMail, brevo } from '../lib/rr.mjs';

export default async (req) => {
  const u = new URL(req.url), e = (u.searchParams.get('e') || '').toLowerCase(), t = u.searchParams.get('t') || '';
  if (!validTeam(t) || !verify(e, t, 'confirm', u.searchParams.get('s'))) return page('Link not valid', '<p>This confirmation link isn\'t valid. Try signing up again from your team\'s page.</p>');
  const teams = (await getTeams(e)) || [];
  const isNew = !teams.includes(t);
  if (isNew) teams.push(t);
  if (!(await setTeams(e, teams.slice(-10)))) return page('Something went wrong', '<p>We couldn\'t save that just now. Please tap the link again in a few minutes.</p>');
  if (isNew) await notifyOwner(e, t, String(u.searchParams.get('n') || '').slice(0, 80));
  const [div, id] = t.split(':');
  return page('You\'re in', `<p>You'll get the RinkRank email every Monday morning, with last week's results, this week's games and the flight standings.</p>
    <p>Every email has a one-tap unsubscribe link.</p><a class="b" href="/#${esc(div)}-team-${esc(id)}" target="_top">Open your team on RinkRank</a>`);
};
export const config = { path: '/api/confirm' };

// A short note to the site owner for each new sign-up. The address lives in the
// RR_NOTIFY setting on Netlify, never in the code. Skipped quietly if it isn't set.
async function notifyOwner(email, team, name) {
  const to = process.env.RR_NOTIFY;
  if (!to) return;
  try {
    const r = await brevo('/contacts?limit=1');
    const total = r.ok && r.data && r.data.count != null ? r.data.count : null;
    const [div, id] = team.split(':');
    await sendMail(to, `New RinkRank subscriber: ${name || team}`,
      `<div style="font:15px/1.5 system-ui,sans-serif;color:#14202a">
        <p><b>${esc(email)}</b> just confirmed the Monday email for <b>${esc(name || team)}</b> (${esc(div.toUpperCase())}).</p>
        ${total != null ? `<p>Total contacts in Brevo: <b>${total}</b>.</p>` : ''}
        <p style="color:#5b6b78;font-size:13px">Team: https://rinkrank.net/#${esc(div)}-team-${esc(id)}</p></div>`);
  } catch (err) { console.log('notify failed', err && err.message); }
}
