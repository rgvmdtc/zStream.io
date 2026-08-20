import sys
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import routing

from resources.lib.sites import sto, aniworld, filmpalast
from resources.lib.utils import resolve_and_play
from resources.lib import updater
import urllib.parse

plugin = routing.Plugin()
addon = xbmcaddon.Addon()

def check_credentials(site):
    email = addon.getSetting(f'{site}_email')
    password = addon.getSetting(f'{site}_password')
    if not email or not password:
        site_name = "s.to" if site == "sto" else "aniworld.to"
        xbmcgui.Dialog().ok("zStream", f"Please enter your email and password for {site_name} in the addon settings.")
        addon.openSettings()
        return False
    return True

@plugin.route('/')
def index():
    # Throttled background self-update: keeps the add-on current straight from
    # GitHub without waiting on Kodi's cached repository list.
    try:
        updater.check_and_update()
    except Exception as e:
        xbmc.log(f"zStream update check skipped: {e}", xbmc.LOGWARNING)

    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(global_search), xbmcgui.ListItem('Global Search'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(sto_index), xbmcgui.ListItem('SerienStream (s.to)'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(aniworld_index), xbmcgui.ListItem('AniWorld (aniworld.to)'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(filmpalast_index), xbmcgui.ListItem('Filmpalast (filmpalast.to)'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(check_updates), xbmcgui.ListItem('Check for updates'), isFolder=False)
    xbmcplugin.endOfDirectory(plugin.handle)

@plugin.route('/check_updates')
def check_updates():
    if not updater.check_and_update(force=True, silent=False):
        xbmc.executebuiltin('Container.Refresh')

@plugin.route('/sto')
def sto_index():
    if check_credentials('sto'):
        sto.index(plugin)

@plugin.route('/sto/list/<path:url>')
def sto_list(url):
    if check_credentials('sto'):
        sto.show_list(plugin, url)

@plugin.route('/sto/series/<path:url>')
def sto_series(url):
    if check_credentials('sto'):
        sto.show_seasons(plugin, url)

@plugin.route('/sto/season/<path:url>')
def sto_season(url):
    if check_credentials('sto'):
        sto.show_episodes(plugin, url)

@plugin.route('/sto/episode/<path:url>')
def sto_episode(url):
    if check_credentials('sto'):
        sto.show_hosters(plugin, url)

@plugin.route('/aniworld')
def aniworld_index():
    if check_credentials('aniworld'):
        aniworld.index(plugin)

@plugin.route('/aniworld/list/<path:url>')
def aniworld_list(url):
    if check_credentials('aniworld'):
        aniworld.show_list(plugin, url)

@plugin.route('/aniworld/anime/<path:url>')
def aniworld_anime(url):
    if check_credentials('aniworld'):
        aniworld.show_seasons(plugin, url)

@plugin.route('/aniworld/season/<path:url>')
def aniworld_season(url):
    if check_credentials('aniworld'):
        aniworld.show_episodes(plugin, url)

@plugin.route('/aniworld/episode/<path:url>')
def aniworld_episode(url):
    if check_credentials('aniworld'):
        aniworld.show_hosters(plugin, url)

@plugin.route('/play/<path:url>')
def play(url):
    resolve_and_play(url, xbmcgui.ListItem())

@plugin.route('/filmpalast')
def filmpalast_index():
    filmpalast.index(plugin)

@plugin.route('/filmpalast/list/<cat>/<page>')
def filmpalast_list(cat, page):
    filmpalast.show_list(plugin, cat, page)

@plugin.route('/filmpalast/detail/<path:slug>')
def filmpalast_detail(slug):
    filmpalast.show_detail(plugin, slug)

@plugin.route('/search')
def global_search():
    query = xbmcgui.Dialog().input('Search movies & series', type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        return
        
    # 1. SerienStream search
    try:
        if check_credentials('sto'):
            sto_results = sto.search(plugin, query)
        else:
            sto_results = []
    except Exception as e:
        xbmc.log(f"zStream sto Search Fail: {str(e)}", xbmc.LOGERROR)
        sto_results = []
        
    # 2. AniWorld search
    try:
        if check_credentials('aniworld'):
            ani_results = aniworld.search(plugin, query)
        else:
            ani_results = []
    except Exception as e:
        xbmc.log(f"zStream aniworld Search Fail: {str(e)}", xbmc.LOGERROR)
        ani_results = []
        
    # 3. Filmpalast search
    try:
        filmpalast_results = filmpalast.search(plugin, query)
    except Exception as e:
        xbmc.log(f"zStream filmpalast Search Fail: {str(e)}", xbmc.LOGERROR)
        filmpalast_results = []
        
    # Render combined results
    for item in sto_results:
        title = f"[s.to] {item['title']}"
        link = item['link']
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/sto/series{link}', xbmcgui.ListItem(title), isFolder=True)
        
    for item in ani_results:
        title = f"[AniWorld] {item['title']}"
        link = item['link']
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/aniworld/anime{link}', xbmcgui.ListItem(title), isFolder=True)
        
    for item in filmpalast_results:
        title = f"[Filmpalast] {item['title']}"
        safe_slug = urllib.parse.quote(item['slug'], safe='')
        route = f'plugin://plugin.video.zstream/filmpalast/detail/{safe_slug}'
        xbmcplugin.addDirectoryItem(plugin.handle, route, xbmcgui.ListItem(title), isFolder=True)

    xbmcplugin.endOfDirectory(plugin.handle)

if __name__ == '__main__':
    plugin.run()
