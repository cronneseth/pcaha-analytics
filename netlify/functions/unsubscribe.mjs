// GET or POST /api/unsubscribe?e&t&s: stop the Monday email for one team (or all when t=all).
// POST is the one-click unsubscribe some mail apps use (List-Unsubscribe-Post).
import { verify, getTeams, setTeams, page } from '../lib/rr.mjs';

export default async (req) => {
  const u = new URL(req.url), e = (u.searchParams.get('e') || '').toLowerCase(), t = u.searchParams.get('t') || '';
  if (!verify(e, t, 'unsub', u.searchParams.get('s'))) return page('Link not valid', '<p>This unsubscribe link isn\'t valid. Reply-free emails can\'t take requests, so please use the link in your latest RinkRank email.</p>');
  const teams = (await getTeams(e)) || [];
  await setTeams(e, t === 'all' ? [] : teams.filter(x => x !== t));
  if (req.method === 'POST') return new Response('', { status: 200 });
  return page('Unsubscribed', `<p>You won't get the Monday email${t === 'all' ? '' : ' for that team'} any more.</p><p>Changed your mind? Sign up again from any team page on RinkRank.</p>`);
};
export const config = { path: '/api/unsubscribe' };
