import urllib.parse
from bs4 import BeautifulSoup
import xbmcgui
import xbmcplugin
import xbmcaddon
from resources.lib.utils import SessionManager, notify

addon = xbmcaddon.Addon()
# serienstream.to is the current s.to. The old s.to domain is dead.
BASE_URL = (addon.getSetting('sto_domain') or "https://serienstream.to").rstrip('/')


def index(plugin):
    xbmcplugin.addDirectoryItem(plugin.handle, 'plugin://plugin.video.zstream/sto/list/serien', xbmcgui.ListItem('Series'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, 'plugin://plugin.video.zstream/sto/list/beliebte-serien', xbmcgui.ListItem('Popular'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_list(plugin, url):
    if not url.startswith('/'):
        url = '/' + url
    html = SessionManager('sto').get_html(BASE_URL + url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    soup = BeautifulSoup(html, 'html.parser')
    added = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/serie/') and href != '/serien' and '/staffel-' not in href and href not in added:
            added.add(href)
            title = a.get('title') or a.text.strip() or href.split('/')[-1].replace('-', ' ').title()
            if title:
                xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/sto/series{href}', xbmcgui.ListItem(title), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_seasons(plugin, url):
    if not url.startswith('/'):
        url = '/' + url
    html = SessionManager('sto').get_html(BASE_URL + url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    soup = BeautifulSoup(html, 'html.parser')
    added = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/staffel-' in href and 'episode-' not in href and href not in added:
            added.add(href)
            title = a.get('title') or a.text.strip() or href.split('/')[-1]
            if title.isdigit() or 'staffel' in title.lower():
                num = title if title.isdigit() else href.rstrip('/').split('-')[-1]
                xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/sto/season{href}', xbmcgui.ListItem(f'Season {num}'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_episodes(plugin, url):
    if not url.startswith('/'):
        url = '/' + url
    html = SessionManager('sto').get_html(BASE_URL + url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    soup = BeautifulSoup(html, 'html.parser')
    added = set()
    # Anchor to the current season path so a prefix season can't cross-match.
    season_prefix = url.rstrip('/') + '/episode-'
    for a in soup.find_all('a', href=True):
        href = a['href']
        if season_prefix in href and href not in added:
            added.add(href)
            ep = href.rstrip('/').split('-')[-1]
            xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/sto/episode{href}', xbmcgui.ListItem(f'Episode {ep}'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)


def show_hosters(plugin, url):
    if not url.startswith('/'):
        url = '/' + url
    html = SessionManager('sto').get_html(BASE_URL + url)
    if not html:
        xbmcplugin.endOfDirectory(plugin.handle)
        return
    soup = BeautifulSoup(html, 'html.parser')
    added = set()

    # New serienstream markup: <button data-play-url="/r?t=..." data-provider-name data-language-label>
    for el in soup.find_all(attrs={"data-play-url": True}):
        href = el.get('data-play-url', '')
        if not href or href in added:
            continue
        added.add(href)
        name = el.get('data-provider-name', 'Hoster')
        lang = el.get('data-language-label', '')
        label = name + (f' [{lang}]' if lang else '')
        # Pass the encrypted /r?t= link straight through; resolve_and_play unwraps it.
        play_url = urllib.parse.quote_plus(BASE_URL + href)
        li = xbmcgui.ListItem(f'Play on {label}')
        li.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/play/{play_url}', li, isFolder=False)

    # Legacy fallback: old /redirect/ anchors, name in child <h4>.
    for a in soup.select('li[data-lang-key] a, div.hosterSiteVideo a'):
        href = a.get('href', '')
        target = a.get('data-link-target', href)
        if target.startswith('/redirect/') and target not in added:
            added.add(target)
            h4 = a.find('h4')
            name = (h4.text.strip() if h4 else a.text.strip()) or 'Hoster'
            play_url = urllib.parse.quote_plus(BASE_URL + target)
            li = xbmcgui.ListItem(f'Play on {name}')
            li.setProperty('IsPlayable', 'true')
            xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/play/{play_url}', li, isFolder=False)

    if not added:
        notify("No streams", "No hosters found for this episode - it may not be available yet.", 'warning', 6000)
    xbmcplugin.endOfDirectory(plugin.handle)


def search(plugin, query):
    # serienstream killed /ajax/search. Live search is GET /suche?term=<q> (server-rendered HTML).
    html = SessionManager('sto').get_html(f"{BASE_URL}/suche?term={urllib.parse.quote_plus(query)}")
    if not html:
        return []
    soup = BeautifulSoup(html, 'html.parser')
    added = set()
    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        # Only series root links (/serie/<slug>, exactly two path segments), dedupe.
        if href.startswith('/serie/') and href.count('/') == 2 and href not in added:
            added.add(href)
            title = a.get('title') or a.text.strip() or href.split('/')[-1].replace('-', ' ').title()
            if title:
                results.append({'title': title, 'link': href})
    return results
