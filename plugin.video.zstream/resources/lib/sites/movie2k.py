import urllib.parse
import requests
import re
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

addon = xbmcaddon.Addon()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'X-Requested-With': 'XMLHttpRequest',
}

# movie2k rotates domains constantly and the origin goes down often.
# Primary comes from settings; the rest are live failover targets.
_FALLBACK_DOMAINS = [
    "https://movie2k.ch",
    "https://movie4k.stream",
    "https://movie4k.sx",
]


def _domains():
    primary = (addon.getSetting('movie2k_domain') or "https://movie2k.ch").rstrip('/')
    ordered = [primary] + [d for d in _FALLBACK_DOMAINS if d != primary]
    seen, out = set(), []
    for d in ordered:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _proxies():
    p = (addon.getSetting('movie2k_proxy') or "").strip()
    return {"http": p, "https": p} if p else None


def _looks_blocked(resp):
    """True if the response is an ISP/Cloudflare interception rather than API data."""
    ct = resp.headers.get('content-type', '')
    if resp.status_code in (403, 502, 503, 522, 523, 524):
        return True
    if 'application/json' in ct:
        return False
    body = resp.text[:400].lower()
    return any(m in body for m in ('cloudflare', 'urheberrechtlichen', '<!doctype html', 'access denied'))


def get_json(path):
    """
    Fetch a movie2k /data/* endpoint with domain failover + optional proxy.
    Returns parsed JSON, or None (with a clear user notification) on total failure.
    `path` must start with '/', e.g. '/data/search/?lang=2&keyword=matrix'.
    """
    proxies = _proxies()
    last_reason = "no domains reachable"
    for base in _domains():
        url = base + path
        try:
            resp = requests.get(url, headers=HEADERS, proxies=proxies, verify=False, timeout=12)
            if _looks_blocked(resp):
                last_reason = f"{base} -> HTTP {resp.status_code} (blocked/origin down)"
                xbmc.log(f"zStream Movie2k blocked: {last_reason}", xbmc.LOGWARNING)
                continue
            resp.raise_for_status()
            return resp.json()
        except ValueError:
            last_reason = f"{base} -> non-JSON body"
            xbmc.log(f"zStream Movie2k non-JSON from {url}", xbmc.LOGWARNING)
            continue
        except Exception as e:
            last_reason = f"{base} -> {type(e).__name__}"
            xbmc.log(f"zStream Movie2k fetch fail {url}: {e}", xbmc.LOGWARNING)
            continue

    xbmc.log(f"zStream Movie2k all domains failed: {last_reason}", xbmc.LOGERROR)
    proxy_hint = "" if proxies else " Set a proxy in settings or use a VPN."
    xbmcgui.Dialog().notification(
        "Movie2k unreachable",
        f"All mirrors blocked or offline.{proxy_hint}",
        xbmcgui.NOTIFICATION_ERROR, 6000)
    return None


def get_original_title(title):
    title = re.sub(r'\s*-\s*(Staffel|Season)\s+\d+', '', title, flags=re.IGNORECASE)
    return title.strip()


def index(plugin):
    xbmcplugin.addDirectoryItem(plugin.handle, 'plugin://plugin.video.zstream/movie2k/movies', xbmcgui.ListItem('Movies'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, 'plugin://plugin.video.zstream/movie2k/series', xbmcgui.ListItem('TV Series'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def movies_index(plugin):
    categories = [('Neu', 'New'), ('Trending', 'Trending'), ('Updates', 'Updates'), ('Views', 'Popular')]
    for cat_id, cat_name in categories:
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/movie2k/list/movies/{cat_id}/1', xbmcgui.ListItem(cat_name), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def series_index(plugin):
    xbmcplugin.addDirectoryItem(plugin.handle, 'plugin://plugin.video.zstream/movie2k/list/tvseries/Views/1', xbmcgui.ListItem('Popular'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_list(plugin, ctype, order_by, page):
    path = (f"/data/browse/?lang=2&keyword=&year=&networks=&rating=&votes=&genre="
            f"&country=&cast=&directors=&type={ctype}&order_by={order_by}&page={page}&limit=20")
    data = get_json(path)
    if not data or 'movies' not in data:
        xbmcplugin.endOfDirectory(plugin.handle)
        return

    for item in data['movies']:
        title = item.get('title', 'Unknown')
        item_id = item.get('_id')
        if not item_id:
            continue

        li = xbmcgui.ListItem(title)
        poster = item.get('poster_path', '')
        if poster:
            if not poster.startswith('http'):
                poster = f"https://image.tmdb.org/t/p/w500{poster}"
            li.setArt({'poster': poster, 'thumb': poster})
        backdrop = item.get('backdrop_path', '')
        if backdrop:
            if not backdrop.startswith('http'):
                backdrop = f"https://image.tmdb.org/t/p/original{backdrop}"
            li.setArt({'fanart': backdrop})

        li.setInfo('video', {
            'title': title,
            'year': int(item.get('year')) if item.get('year') else None,
            'rating': float(item.get('rating')) if item.get('rating') else None,
            'genre': item.get('genres', ''),
        })

        if ctype == 'movies':
            route_url = f'plugin://plugin.video.zstream/movie2k/movie/{item_id}'
        else:
            safe_title = urllib.parse.quote_plus(get_original_title(title))
            route_url = f'plugin://plugin.video.zstream/movie2k/seasons/{safe_title}'
        xbmcplugin.addDirectoryItem(plugin.handle, route_url, li, isFolder=True)

    pager = data.get('pager', {})
    current_page = int(page)
    if current_page < pager.get('totalPages', current_page):
        xbmcplugin.addDirectoryItem(
            plugin.handle,
            f'plugin://plugin.video.zstream/movie2k/list/{ctype}/{order_by}/{current_page + 1}',
            xbmcgui.ListItem('>> Next Page'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_seasons(plugin, original_title):
    decoded_title = urllib.parse.unquote_plus(original_title)
    seasons = get_json(f"/data/seasons/?lang=2&original_title={urllib.parse.quote(decoded_title)}")
    if not seasons:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    for s in seasons:
        s_num = s.get('s', 1)
        s_id = s.get('_id')
        li = xbmcgui.ListItem(s.get('title', f"Season {s_num}"))
        poster = s.get('poster_path_season') or s.get('poster_path', '')
        if poster:
            if not poster.startswith('http'):
                poster = f"https://image.tmdb.org/t/p/w500{poster}"
            li.setArt({'poster': poster, 'thumb': poster})
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/movie2k/season/{s_id}', li, isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_episodes(plugin, season_id):
    watch_data = get_json(f"/data/watch/?_id={season_id}")
    if not watch_data or 'streams' not in watch_data:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    episodes = sorted({stream.get('e') for stream in watch_data['streams'] if stream.get('e') is not None})
    poster = watch_data.get('poster_path_season') or watch_data.get('poster_path', '')
    if poster and not poster.startswith('http'):
        poster = f"https://image.tmdb.org/t/p/w500{poster}"
    backdrop = watch_data.get('backdrop_path', '')
    if backdrop and not backdrop.startswith('http'):
        backdrop = f"https://image.tmdb.org/t/p/original{backdrop}"
    for ep in episodes:
        li = xbmcgui.ListItem(f"Episode {ep}")
        if poster:
            li.setArt({'poster': poster, 'thumb': poster})
        if backdrop:
            li.setArt({'fanart': backdrop})
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/movie2k/episode/{season_id}/{ep}', li, isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def get_hoster_name(stream_url):
    try:
        host = urllib.parse.urlparse(stream_url).netloc or "Hoster"
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return "Hoster"


def _render_hosters(plugin, streams):
    seen = set()
    for s in streams:
        stream_url = s.get('stream')
        if not stream_url:
            continue
        name = get_hoster_name(stream_url)
        if name in seen:
            continue
        seen.add(name)
        release = s.get('release', '').strip()
        li = xbmcgui.ListItem(f"Play on {name}" + (f" ({release})" if release else ""))
        li.setProperty('IsPlayable', 'true')
        safe_url = urllib.parse.quote_plus(stream_url)
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/play/{safe_url}', li, isFolder=False)


def show_movie_hosters(plugin, movie_id):
    watch_data = get_json(f"/data/watch/?_id={movie_id}")
    if not watch_data or 'streams' not in watch_data:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    _render_hosters(plugin, watch_data['streams'])
    xbmcplugin.endOfDirectory(plugin.handle)


def show_episode_hosters(plugin, season_id, episode_num):
    watch_data = get_json(f"/data/watch/?_id={season_id}")
    if not watch_data or 'streams' not in watch_data:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    ep_num = int(episode_num)
    _render_hosters(plugin, [s for s in watch_data['streams'] if s.get('e') == ep_num])
    xbmcplugin.endOfDirectory(plugin.handle)


def search(plugin, query):
    results = get_json(f"/data/search/?lang=2&keyword={urllib.parse.quote(query)}")
    if not results:
        return []
    items = []
    for item in results:
        item_id = item.get('_id')
        if not item_id:
            continue
        title = item.get('title', 'Unknown')
        items.append({
            'title': title,
            'id': item_id,
            'tv': item.get('tv', 0),
            'original_title': get_original_title(title),
        })
    return items
