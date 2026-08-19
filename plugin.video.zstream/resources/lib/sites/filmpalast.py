import re
import urllib.parse
import requests
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

addon = xbmcaddon.Addon()
BASE_URL = (addon.getSetting('filmpalast_domain') or "https://filmpalast.to").rstrip('/')

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {'User-Agent': USER_AGENT}


def _get_html(url):
    try:
        resp = requests.get(url, headers=HEADERS, verify=False, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        xbmc.log(f"zStream Filmpalast fetch error ({url}): {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Filmpalast", "Failed to load page", xbmcgui.NOTIFICATION_ERROR)
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
    for it in items:
        li = xbmcgui.ListItem(it['title'])
        li.setInfo('video', {'title': it['title']})
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
        xbmcgui.Dialog().notification("Filmpalast", "No streams found for this title",
                                      xbmcgui.NOTIFICATION_INFO)
    for provider, stream_url in hosters:
        li = xbmcgui.ListItem(f'Play on {provider}')
        li.setProperty('IsPlayable', 'true')
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
