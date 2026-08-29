import re
import urllib.parse
import requests
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
from resources.lib.utils import notify

addon = xbmcaddon.Addon()
BASE_URL = (addon.getSetting('kinoger_domain') or "https://kinoger.com").rstrip('/')

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {'User-Agent': USER_AGENT, 'Accept-Language': 'de-DE,de;q=0.9'}

# Only these are real video hosts; the pw.show arrays also contain related-post
# links, poster images and social-share URLs we must ignore.
_HOSTER_RE = re.compile(r'^https?://[a-z0-9.-]+/(?:embed|e|v|d|f)/[A-Za-z0-9]+', re.I)


def _get(url, post=None):
    try:
        if post is not None:
            r = requests.post(url, data=post, headers=HEADERS, verify=False, timeout=15)
        else:
            r = requests.get(url, headers=HEADERS, verify=False, timeout=15)
        r.raise_for_status()
        return r.text
    except requests.exceptions.HTTPError as e:
        code = getattr(e.response, 'status_code', '?')
        notify("Kinoger", f"Server returned HTTP {code}.", 'warning', 5000)
        xbmc.log(f"zStream Kinoger HTTP {code} ({url})", xbmc.LOGERROR)
    except requests.exceptions.Timeout:
        notify("Kinoger", "Timed out. Try again or check your VPN.", 'error', 5000)
    except Exception as e:
        notify("Kinoger", "Couldn't reach Kinoger. Check connection / VPN.", 'error', 5000)
        xbmc.log(f"zStream Kinoger fetch error ({url}): {e}", xbmc.LOGERROR)
    return None


def _post_title(url, html_scope):
    """Title for a /stream/ post, from its own anchor text if present."""
    m = re.search(r'href="' + re.escape(url) + r'"[^>]*>\s*([^<]{2,80})</a>', html_scope)
    if m and m.group(1).strip():
        return m.group(1).strip()
    slug = url.rstrip('/').split('/')[-1]
    slug = re.sub(r'^\d+-', '', slug).replace('-stream', '').replace('.html', '')
    return slug.replace('-', ' ').title()


def parse_listing(html):
    """Ordered, de-duplicated posts: {'url','title','poster'} from any list page."""
    titles = {}
    for u, t in re.findall(r'<a href="(https?://[^"]*?/stream/\d+-[^"]+\.html)"[^>]*>([^<]{2,80})</a>', html):
        t = t.strip()
        if t and u not in titles:
            titles[u] = t
    posters = {}
    for u, p in re.findall(r'<a href="(https?://[^"]*?/stream/\d+-[^"]+\.html)"[^>]*>\s*<div[^>]*>\s*<img[^>]+src="([^"]+)"', html):
        posters.setdefault(u, p)

    items, seen = [], set()
    for u in re.findall(r'https?://[^"]*?/stream/\d+-[^"]+\.html', html):
        if u in seen:
            continue
        seen.add(u)
        items.append({'url': u, 'title': titles.get(u) or _post_title(u, html), 'poster': posters.get(u, '')})
    return items


def parse_players(html):
    """
    Return the pw.show groups as a list of lists of hoster embed URLs.
    One group == a movie's mirror set; multiple groups == series episodes.
    """
    groups = []
    for block in re.findall(r'pw\.show\(\s*\d+\s*,\s*(\[\[.*?\]\])\s*\)', html, re.S):
        try:
            # turn the JS array-of-arrays into python groups of hoster URLs
            for grp in re.findall(r'\[((?:\s*[\'"][^\'"]+[\'"]\s*,?)+)\]', block):
                urls = [u.strip() for u in re.findall(r'[\'"]([^\'"]+)[\'"]', grp)]
                hosters, seen = [], set()
                for u in urls:
                    host = urllib.parse.urlparse(u).netloc.lower()
                    if _HOSTER_RE.match(u) and host not in seen:
                        seen.add(host)
                        hosters.append(u)
                if hosters:
                    groups.append(hosters)
        except Exception as e:
            xbmc.log(f"zStream Kinoger player parse error: {e}", xbmc.LOGWARNING)
    return groups


def index(plugin):
    xbmcplugin.setContent(plugin.handle, 'movies')
    xbmcplugin.addDirectoryItem(
        plugin.handle, 'plugin://plugin.video.zstream/kinoger/list/0',
        xbmcgui.ListItem('Neu / Latest'), isFolder=True)
    for label, slug in [('Action', 'action'), ('Horror', 'horror'), ('Thriller', 'thriller'),
                        ('Sci-Fi', 'sci-fi'), ('Animation', 'animation'), ('Drama', 'drama'),
                        ('Abenteuer', 'abenteuer')]:
        safe = urllib.parse.quote(f'genre/{slug}', safe='')
        xbmcplugin.addDirectoryItem(
            plugin.handle, f'plugin://plugin.video.zstream/kinoger/cat/{safe}/1',
            xbmcgui.ListItem(label), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def _render_list(plugin, items, next_url):
    xbmcplugin.setContent(plugin.handle, 'movies')
    for it in items:
        li = xbmcgui.ListItem(it['title'])
        li.setInfo('video', {'title': it['title'], 'mediatype': 'movie'})
        if it['poster']:
            li.setArt({'poster': it['poster'], 'thumb': it['poster'], 'fanart': it['poster']})
        safe_url = urllib.parse.quote(it['url'], safe='')
        li.setProperty('IsPlayable', 'false')
        xbmcplugin.addDirectoryItem(
            plugin.handle, f'plugin://plugin.video.zstream/kinoger/detail/{safe_url}', li, isFolder=True)
    if items and next_url:
        xbmcplugin.addDirectoryItem(plugin.handle, next_url, xbmcgui.ListItem('>> Next Page'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_list(plugin, page):
    page = int(page)
    url = BASE_URL + (f"/page/{page}/" if page > 1 else "/")
    html = _get(url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    items = parse_listing(html)
    _render_list(plugin, items, f'plugin://plugin.video.zstream/kinoger/list/{page + 1}')


def show_category(plugin, cat, page):
    cat = urllib.parse.unquote(cat).strip('/')
    page = int(page)
    url = f"{BASE_URL}/{cat}/" + (f"page/{page}/" if page > 1 else "")
    html = _get(url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    items = parse_listing(html)
    safe_cat = urllib.parse.quote(cat, safe='')
    _render_list(plugin, items, f'plugin://plugin.video.zstream/kinoger/cat/{safe_cat}/{page + 1}')


def show_detail(plugin, post_url):
    post_url = urllib.parse.unquote(post_url)
    html = _get(post_url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return

    title = (re.search(r'<meta property="og:title" content="([^"]+)"', html) or [None, ''])[1]
    poster = (re.search(r'<meta property="og:image" content="([^"]+)"', html) or [None, ''])[1]
    groups = parse_players(html)

    if not groups:
        notify("Kinoger", "No playable sources for this title.", 'warning', 6000)
        xbmcplugin.endOfDirectory(plugin.handle)
        return

    art = {'poster': poster, 'thumb': poster, 'fanart': poster} if poster else {}
    xbmcplugin.setContent(plugin.handle, 'movies')

    if len(groups) == 1:
        # Movie: list each mirror as a Play option (VOE/Firestream/etc. resolve to
        # HLS with native Kodi quality selection; fsst falls back to direct mp4).
        for stream_url in groups[0]:
            host = urllib.parse.urlparse(stream_url).netloc.replace('www.', '')
            li = xbmcgui.ListItem(f'Play on {host}')
            li.setProperty('IsPlayable', 'true')
            li.setInfo('video', {'title': title, 'mediatype': 'movie'})
            if art:
                li.setArt(art)
            safe = urllib.parse.quote_plus(stream_url)
            xbmcplugin.addDirectoryItem(
                plugin.handle, f'plugin://plugin.video.zstream/play/{safe}', li, isFolder=False)
    else:
        # Series: each group is an episode -> folder of that episode's mirrors.
        for i, grp in enumerate(groups, 1):
            li = xbmcgui.ListItem(f'Episode {i}')
            if art:
                li.setArt(art)
            payload = urllib.parse.quote(','.join(grp), safe='')
            xbmcplugin.addDirectoryItem(
                plugin.handle, f'plugin://plugin.video.zstream/kinoger/episode/{payload}', li, isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_episode(plugin, payload):
    urls = [u for u in urllib.parse.unquote(payload).split(',') if u]
    xbmcplugin.setContent(plugin.handle, 'episodes')
    for stream_url in urls:
        host = urllib.parse.urlparse(stream_url).netloc.replace('www.', '')
        li = xbmcgui.ListItem(f'Play on {host}')
        li.setProperty('IsPlayable', 'true')
        safe = urllib.parse.quote_plus(stream_url)
        xbmcplugin.addDirectoryItem(
            plugin.handle, f'plugin://plugin.video.zstream/play/{safe}', li, isFolder=False)
    xbmcplugin.endOfDirectory(plugin.handle)


def search(plugin, query):
    html = _get(f"{BASE_URL}/index.php?do=search",
                post={'do': 'search', 'subaction': 'search', 'story': query})
    if not html:
        return []
    results, seen = [], set()
    for u, t in re.findall(r'href="(https?://[^"]*?/stream/\d+-[^"]+\.html)"[^>]*>\s*([^<]{2,70})', html):
        t = t.strip()
        if u not in seen and t:
            seen.add(u)
            results.append({'url': u, 'title': t})
    return results
