// GET /api/confirm?e&t&s: the link in the confirmation email. Adds the team to the contact in Brevo.
import { SITE, verify, getTeams, setTeams, page, validTeam, esc } from '../lib/rr.mjs';

export default async (req) => {
  const u = new URL(req.url), e = (u.searchParams.get('e') || '').toLowerCase(), t = u.searchParams.get('t') || '';
  if (!validTeam(t) || !verify(e, t, 'confirm', u.searchParams.get('s'))) return page('Link not valid', '<p>This confirmation link isn\'t valid. Try signing up again from your team\'s page.</p>');
  const teams = (await getTeams(e)) || [];
  if (!teams.includes(t)) teams.push(t);
  if (!(await setTeams(e, teams.slice(-10)))) return page('Something went wrong', '<p>We couldn\'t save that just now. Please tap the link again in a few minutes.</p>');
  const [div, id] = t.split(':');
  return page('You\'re in', `<p>You'll get the RinkRank email every Monday morning, with last week's results, this week's games and the flight standings.</p>
    <p>Every email has a one-tap unsubscribe link.</p><a class="b" href="${SITE}/#${esc(div)}-team-${esc(id)}">Back to your team</a>`);
};
export const config = { path: '/api/confirm' };
