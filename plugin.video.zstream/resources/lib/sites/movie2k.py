import urllib.parse
import requests
import json
import re
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

addon = xbmcaddon.Addon()
BASE_URL = "https://movie2k.ch"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

def get_json(url):
    try:
        resp = requests.get(url, headers=HEADERS, verify=False, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        xbmc.log(f"zStream Movie2k JSON Error ({url}): {str(e)}", xbmc.LOGERROR)
        return None

def get_original_title(title):
    # Remove things like " - Staffel 1", " - Season 2", etc.
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
    url = f"{BASE_URL}/data/browse/?lang=2&keyword=&year=&networks=&rating=&votes=&genre=&country=&cast=&directors=&type={ctype}&order_by={order_by}&page={page}&limit=20"
    data = get_json(url)
    if not data or 'movies' not in data:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
        
    for item in data['movies']:
        title = item.get('title', 'Unknown')
        item_id = item.get('_id')
        if not item_id:
            continue
            
        li = xbmcgui.ListItem(title)
        
        # Set graphics if present
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
            
        # Set info labels
        info = {
            'title': title,
            'year': int(item.get('year')) if item.get('year') else None,
            'rating': float(item.get('rating')) if item.get('rating') else None,
            'genre': item.get('genres', '')
        }
        li.setInfo('video', info)
        
        if ctype == 'movies':
            # Skip season folder completely, go straight to movie watch page/hosters list
            route_url = f'plugin://plugin.video.zstream/movie2k/movie/{item_id}'
        else:
            # TV Series go to seasons folder
            orig_title = get_original_title(title)
            safe_title = urllib.parse.quote_plus(orig_title)
            route_url = f'plugin://plugin.video.zstream/movie2k/seasons/{safe_title}'
            
        xbmcplugin.addDirectoryItem(plugin.handle, route_url, li, isFolder=True)
        
    # Check for next page
    pager = data.get('pager', {})
    current_page = int(page)
    total_pages = pager.get('totalPages', current_page)
    if current_page < total_pages:
        next_page = current_page + 1
        xbmcplugin.addDirectoryItem(
            plugin.handle, 
            f'plugin://plugin.video.zstream/movie2k/list/{ctype}/{order_by}/{next_page}', 
            xbmcgui.ListItem('>> Next Page'), 
            isFolder=True
        )
        
    xbmcplugin.endOfDirectory(plugin.handle)

def show_seasons(plugin, original_title):
    decoded_title = urllib.parse.unquote_plus(original_title)
    url = f"{BASE_URL}/data/seasons/?lang=2&original_title={urllib.parse.quote(decoded_title)}"
    seasons = get_json(url)
    if not seasons:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
        
    for s in seasons:
        s_num = s.get('s', 1)
        s_id = s.get('_id')
        s_title = s.get('title', f"Season {s_num}")
        
        li = xbmcgui.ListItem(s_title)
        
        poster = s.get('poster_path_season') or s.get('poster_path', '')
        if poster:
            if not poster.startswith('http'):
                poster = f"https://image.tmdb.org/t/p/w500{poster}"
            li.setArt({'poster': poster, 'thumb': poster})
            
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/movie2k/season/{s_id}', li, isFolder=True)
        
    xbmcplugin.endOfDirectory(plugin.handle)

def show_episodes(plugin, season_id):
    url = f"{BASE_URL}/data/watch/?_id={season_id}"
    watch_data = get_json(url)
    if not watch_data or 'streams' not in watch_data:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
        
    # Extract unique episode numbers
    episodes = sorted(list(set(stream.get('e') for stream in watch_data['streams'] if stream.get('e') is not None)))
    
    # Backdrop/poster if available
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
        parsed = urllib.parse.urlparse(stream_url)
        host = parsed.netloc or "Hoster"
        if host.startswith("www."):
            host = host[4:]
        return host
    except:
        return "Hoster"

def show_movie_hosters(plugin, movie_id):
    url = f"{BASE_URL}/data/watch/?_id={movie_id}"
    watch_data = get_json(url)
    if not watch_data or 'streams' not in watch_data:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
        
    seen_hosters = set()
    for s in watch_data['streams']:
        stream_url = s.get('stream')
        if not stream_url:
            continue
            
        hoster_name = get_hoster_name(stream_url)
        if hoster_name in seen_hosters:
            continue
        seen_hosters.add(hoster_name)
        
        release = s.get('release', '').strip()
        release_suffix = f" ({release})" if release else ""
        
        li = xbmcgui.ListItem(f"Play on {hoster_name}{release_suffix}")
        li.setProperty('IsPlayable', 'true')
        
        safe_url = urllib.parse.quote_plus(stream_url)
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/play/{safe_url}', li, isFolder=False)
        
    xbmcplugin.endOfDirectory(plugin.handle)

def show_episode_hosters(plugin, season_id, episode_num):
    url = f"{BASE_URL}/data/watch/?_id={season_id}"
    watch_data = get_json(url)
    if not watch_data or 'streams' not in watch_data:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
        
    ep_num = int(episode_num)
    matching_streams = [s for s in watch_data['streams'] if s.get('e') == ep_num]
    
    seen_hosters = set()
    for s in matching_streams:
        stream_url = s.get('stream')
        if not stream_url:
            continue
            
        hoster_name = get_hoster_name(stream_url)
        if hoster_name in seen_hosters:
            continue
        seen_hosters.add(hoster_name)
        
        release = s.get('release', '').strip()
        release_suffix = f" ({release})" if release else ""
        
        li = xbmcgui.ListItem(f"Play on {hoster_name}{release_suffix}")
        li.setProperty('IsPlayable', 'true')
        
        safe_url = urllib.parse.quote_plus(stream_url)
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/play/{safe_url}', li, isFolder=False)
        
    xbmcplugin.endOfDirectory(plugin.handle)

def search(plugin, query):
    url = f"{BASE_URL}/data/search/?lang=2&keyword={urllib.parse.quote(query)}"
    results = get_json(url)
    if not results:
        return []
        
    items = []
    for item in results:
        title = item.get('title', 'Unknown')
        item_id = item.get('_id')
        tv = item.get('tv', 0)
        
        if not item_id:
            continue
            
        items.append({
            'title': title,
            'id': item_id,
            'tv': tv,
            'original_title': get_original_title(title)
        })
    return items
