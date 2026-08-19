import re
import urllib.parse
import requests
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
from resources.lib.utils import notify

addon = xbmcaddon.Addon()
BASE_URL = (addon.getSetting('filmpalast_domain') or "https://filmpalast.to").rstrip('/')

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {'User-Agent': USER_AGENT}


def _poster(slug, size=450):
    """Filmpalast cover art follows a fixed path derived from the slug."""
    return f"{BASE_URL}/files/movies/{size}/{slug}.jpg"


def _get_html(url):
    try:
        resp = requests.get(url, headers=HEADERS, verify=False, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.HTTPError as e:
        code = getattr(e.response, 'status_code', '?')
        if code == 404:
            notify("Not found", "This page no longer exists on Filmpalast (404).", 'warning', 6000)
        else:
            notify("Filmpalast error", f"Server returned HTTP {code}.", 'error', 6000)
        xbmc.log(f"zStream Filmpalast HTTP {code} ({url})", xbmc.LOGERROR)
        return None
    except requests.exceptions.Timeout:
        notify("Timeout", "Filmpalast took too long to respond. Try again or check your VPN.", 'error', 6000)
        xbmc.log(f"zStream Filmpalast timeout ({url})", xbmc.LOGERROR)
        return None
    except Exception as e:
        notify("Connection error", "Couldn't reach Filmpalast. Check your connection / VPN.", 'error', 6000)
        xbmc.log(f"zStream Filmpalast fetch error ({url}): {e}", xbmc.LOGERROR)
        return None


def parse_listing(html):
    """Return ordered, de-duplicated [{'title','slug'}] from any catalog/search page."""
    items, seen = [], set()
    for m in re.finditer(r'href="(?://[^/]+)?/stream/([a-z0-9-]+)"[^>]*title="([^"]+)"', html):
        slug, title = m.group(1), m.group(2).strip()
        if slug not in seen:
            seen.add(slug)
            items.append({'title': title, 'slug': slug})
    # Fallback: some pages put title in link text, not the title attr.
    if not items:
        for m in re.finditer(r'href="(?://[^/]+)?/stream/([a-z0-9-]+)"[^>]*>([^<]+)<', html):
            slug, title = m.group(1), m.group(2).strip()
            if slug and title and slug not in seen:
                seen.add(slug)
                items.append({'title': title, 'slug': slug})
    return items


def parse_hosters(html):
    """
    Return ordered, de-duplicated [(provider_name, stream_url)] for one title.
    The real link lives in data-player-url; commented <!--<a href=...>--> decoys
    are stripped first, then each hostName is paired with the next real anchor.
    """
    # The hoster list contains nested <ul>s, so don't bound on the first </ul>.
    # Take everything from the container start to its enclosing </section>.
    idx = html.find('currentStreamLinks')
    block = html[idx:] if idx >= 0 else html
    end = block.find('</section>')
    if end > 0:
        block = block[:end]
    block = re.sub(r'<!--.*?-->', '', block, flags=re.S)  # remove commented decoys

    out, name = [], None
    for tok in re.finditer(r'<p class="hostName">([^<]+)</p>|<a\b([^>]*?)>', block):
        if tok.group(1):
            name = tok.group(1).strip()
        else:
            attrs = tok.group(2)
            url = (re.search(r'data-player-url="([^"]+)"', attrs)
                   or re.search(r'href="(https?://[^"]+)"', attrs))
            if url and name:
                out.append((name, url.group(1)))
                name = None

    seen, res = set(), []
    for prov, url in out:
        if url not in seen:
            seen.add(url)
            res.append((prov, url))
    return res


def index(plugin):
    entries = [
        ('New Movies', 'movies/new'),
        ('Top Movies', 'movies/top'),
        ('Series', 'serien'),
    ]
    for label, path in entries:
        safe = urllib.parse.quote(path, safe='')
        xbmcplugin.addDirectoryItem(
            plugin.handle,
            f'plugin://plugin.video.zstream/filmpalast/list/{safe}/1',
            xbmcgui.ListItem(label), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_list(plugin, cat, page):
    cat = urllib.parse.unquote(cat).strip('/')
    page = int(page)
    url = f"{BASE_URL}/{cat}" + (f"/page/{page}" if page > 1 else "")
    html = _get_html(url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return

    items = parse_listing(html)
    if not items:
        notify("Filmpalast", "Nothing found on this page.", 'info', 4000)

    xbmcplugin.setContent(plugin.handle, 'movies')
    for it in items:
        li = xbmcgui.ListItem(it['title'])
        li.setInfo('video', {'title': it['title'], 'mediatype': 'movie'})
        poster = _poster(it['slug'])
        li.setArt({'poster': poster, 'thumb': poster, 'icon': poster, 'fanart': poster})
        safe_slug = urllib.parse.quote(it['slug'], safe='')
        xbmcplugin.addDirectoryItem(
            plugin.handle,
            f'plugin://plugin.video.zstream/filmpalast/detail/{safe_slug}',
            li, isFolder=True)

    if items:
        safe_cat = urllib.parse.quote(cat, safe='')
        xbmcplugin.addDirectoryItem(
            plugin.handle,
            f'plugin://plugin.video.zstream/filmpalast/list/{safe_cat}/{page + 1}',
            xbmcgui.ListItem('>> Next Page'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_detail(plugin, slug):
    slug = urllib.parse.unquote(slug)
    html = _get_html(f"{BASE_URL}/stream/{slug}")
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return

    hosters = parse_hosters(html)
    if not hosters:
        notify("No streams", "No playable sources for this title yet - it may be new or removed.", 'warning', 6000)
        xbmcplugin.endOfDirectory(plugin.handle)
        return

    # Pull poster + plot so each provider entry shows real artwork/metadata.
    poster = _poster(slug)
    plot_m = re.search(r'itemprop="description">\s*([^<]{5,})', html)
    plot = re.sub(r'\s+', ' ', plot_m.group(1)).strip() if plot_m else ''
    year_m = re.search(r'>(\d{4})<', html)
    info = {'title': slug.replace('-', ' ').title(), 'mediatype': 'movie'}
    if plot:
        info['plot'] = plot
    if year_m:
        info['year'] = int(year_m.group(1))

    xbmcplugin.setContent(plugin.handle, 'movies')
    for provider, stream_url in hosters:
        li = xbmcgui.ListItem(f'Play on {provider}')
        li.setProperty('IsPlayable', 'true')
        li.setInfo('video', info)
        li.setArt({'poster': poster, 'thumb': poster, 'fanart': poster})
        safe_url = urllib.parse.quote_plus(stream_url)
        xbmcplugin.addDirectoryItem(
            plugin.handle,
            f'plugin://plugin.video.zstream/play/{safe_url}',
            li, isFolder=False)
    xbmcplugin.endOfDirectory(plugin.handle)


def search(plugin, query):
    html = _get_html(f"{BASE_URL}/search/title/{urllib.parse.quote(query)}")
    if not html:
        return []
    return parse_listing(html)
