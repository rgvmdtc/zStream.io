import urllib.parse
from bs4 import BeautifulSoup
import xbmcgui
import xbmcplugin
import xbmcaddon
from resources.lib.utils import SessionManager
import re

addon = xbmcaddon.Addon()
BASE_URL = addon.getSetting('aniworld_domain') or "https://aniworld.to"
BASE_URL = BASE_URL.rstrip('/')

def index(plugin):
    xbmcplugin.addDirectoryItem(plugin.handle, 'plugin://plugin.video.zstream/aniworld/list/animes', xbmcgui.ListItem('Anime'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, 'plugin://plugin.video.zstream/aniworld/list/beliebte-animes', xbmcgui.ListItem('Popular'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)

def show_list(plugin, url):
    if not url.startswith('/'): url = '/' + url
    full_url = BASE_URL + url
    html = SessionManager('aniworld').get_html(full_url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    soup = BeautifulSoup(html, 'html.parser')
    anime_links = soup.find_all('a', href=True)
    added = set()
    for a in anime_links:
        href = a['href']
        if href.startswith('/anime/') and href != '/animes' and href not in added:
            added.add(href)
            title = a.get('title') or a.text.strip() or href.split('/')[-1]
            if title:
                xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/aniworld/anime{href}', xbmcgui.ListItem(title), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)

def show_seasons(plugin, url):
    if not url.startswith('/'): url = '/' + url
    full_url = BASE_URL + url
    html = SessionManager('aniworld').get_html(full_url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    soup = BeautifulSoup(html, 'html.parser')
    season_links = soup.find_all('a', href=True)
    added = set()
    for a in season_links:
        href = a['href']
        if '/staffel-' in href and href not in added and not 'episode-' in href:
            added.add(href)
            title = a.get('title') or a.text.strip() or href.split('/')[-1]
            if title.isdigit() or 'staffel' in title.lower():
                xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/aniworld/season{href}', xbmcgui.ListItem(f'Season {title}'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)

def show_episodes(plugin, url):
    if not url.startswith('/'): url = '/' + url
    full_url = BASE_URL + url
    html = SessionManager('aniworld').get_html(full_url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    soup = BeautifulSoup(html, 'html.parser')
    episode_links = soup.find_all('a', href=True)
    added = set()
    for a in episode_links:
        href = a['href']
        if '/episode-' in href and url in href and href not in added:
            added.add(href)
            title = a.get('title') or a.text.strip() or href.split('/')[-1]
            if title.isdigit() or 'episode' in title.lower():
                xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/aniworld/episode{href}', xbmcgui.ListItem(f'Episode {title}'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)

def show_hosters(plugin, url):
    if not url.startswith('/'): url = '/' + url
    full_url = BASE_URL + url
    session_manager = SessionManager('aniworld')
    html = session_manager.get_html(full_url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    soup = BeautifulSoup(html, 'html.parser')
    
    # Very basic attempt to find redirect hoster links on the episode page
    hoster_elements = soup.find_all(attrs={"data-play-url": True})
    
    # Also fallback to old 'a' tags just in case
    hoster_links = soup.select('ul.hosterTabs a, div.hosterSiteVideo a, li[data-lang-key] a')
    
    added_hosters = set()
    
    for el in hoster_elements:
        href = el.get('data-play-url', '')
        if href and href not in added_hosters:
            added_hosters.add(href)
            hoster_name = el.get('data-provider-name', 'Hoster')
            redirect_url = BASE_URL + href
            
            try:
                resp = session_manager.session.get(redirect_url, allow_redirects=False, verify=False)
                final_url = resp.headers.get('Location', redirect_url)
            except:
                final_url = redirect_url
                
            li = xbmcgui.ListItem(f'Play on {hoster_name}')
            li.setProperty('IsPlayable', 'true')
            safe_url = urllib.parse.quote_plus(final_url)
            xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/play/{safe_url}', li, isFolder=False)

    for a in hoster_links:
        href = a.get('href', '')
        if href.startswith('/redirect/') and href not in added_hosters:
            added_hosters.add(href)
            hoster_name = a.text.strip() or 'Hoster'
            redirect_url = BASE_URL + href
            try:
                resp = session_manager.session.get(redirect_url, allow_redirects=False, verify=False)
                final_url = resp.headers.get('Location', redirect_url)
            except:
                final_url = redirect_url
                
            li = xbmcgui.ListItem(f'Play on {hoster_name}')
            li.setProperty('IsPlayable', 'true')
            safe_url = urllib.parse.quote_plus(final_url)
            xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/play/{safe_url}', li, isFolder=False)
            
    xbmcplugin.endOfDirectory(plugin.handle)

def search(plugin, query):
    url = BASE_URL + "/ajax/search"
    session_manager = SessionManager('aniworld')
    headers = {
        'User-Agent': session_manager.session.headers.get('User-Agent', ''),
        'X-Requested-With': 'XMLHttpRequest'
    }
    try:
        resp = session_manager.session.post(url, data={'keyword': query}, headers=headers, verify=False, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        
        parsed_results = []
        for r in results:
            raw_title = r.get('title', '')
            # Clean HTML tags like <em> from the title
            clean_title = re.sub(r'<[^>]*>', '', raw_title).strip()
            link = r.get('link', '')
            if clean_title and link:
                parsed_results.append({
                    'title': clean_title,
                    'link': link
                })
        return parsed_results
    except Exception as e:
        xbmc.log(f"zStream Aniworld Search Error: {str(e)}", xbmc.LOGERROR)
        return []

