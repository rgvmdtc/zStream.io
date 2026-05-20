import sys
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import routing

from resources.lib.sites import sto, aniworld, movie2k
from resources.lib.utils import resolve_and_play
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
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(global_search), xbmcgui.ListItem('Global Search'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(sto_index), xbmcgui.ListItem('SerienStream (s.to)'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(aniworld_index), xbmcgui.ListItem('AniWorld (aniworld.to)'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(movie2k_index), xbmcgui.ListItem('Movie2k (movie2k.ch)'), isFolder=True)
    xbmcplugin.endOfDirectory(plugin.handle)

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

@plugin.route('/movie2k')
def movie2k_index():
    movie2k.index(plugin)

@plugin.route('/movie2k/movies')
def movie2k_movies():
    movie2k.movies_index(plugin)

@plugin.route('/movie2k/series')
def movie2k_series():
    movie2k.series_index(plugin)

@plugin.route('/movie2k/list/<ctype>/<order_by>/<page>')
def movie2k_list(ctype, order_by, page):
    movie2k.show_list(plugin, ctype, order_by, page)

@plugin.route('/movie2k/seasons/<path:original_title>')
def movie2k_seasons(original_title):
    movie2k.show_seasons(plugin, original_title)

@plugin.route('/movie2k/season/<path:season_id>')
def movie2k_season(season_id):
    movie2k.show_episodes(plugin, season_id)

@plugin.route('/movie2k/episode/<path:season_id>/<int:episode_num>')
def movie2k_episode(season_id, episode_num):
    movie2k.show_episode_hosters(plugin, season_id, episode_num)

@plugin.route('/movie2k/movie/<path:movie_id>')
def movie2k_movie(movie_id):
    movie2k.show_movie_hosters(plugin, movie_id)

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
        
    # 3. Movie2k search
    try:
        movie2k_results = movie2k.search(plugin, query)
    except Exception as e:
        xbmc.log(f"zStream movie2k Search Fail: {str(e)}", xbmc.LOGERROR)
        movie2k_results = []
        
    # Render combined results
    for item in sto_results:
        title = f"[s.to] {item['title']}"
        link = item['link']
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/sto/series{link}', xbmcgui.ListItem(title), isFolder=True)
        
    for item in ani_results:
        title = f"[AniWorld] {item['title']}"
        link = item['link']
        xbmcplugin.addDirectoryItem(plugin.handle, f'plugin://plugin.video.zstream/aniworld/anime{link}', xbmcgui.ListItem(title), isFolder=True)
        
    for item in movie2k_results:
        if item['tv'] == 1:
            title = f"[Movie2k] (Series) {item['title']}"
            safe_title = urllib.parse.quote_plus(item['original_title'])
            route = f'plugin://plugin.video.zstream/movie2k/seasons/{safe_title}'
        else:
            title = f"[Movie2k] (Movie) {item['title']}"
            route = f'plugin://plugin.video.zstream/movie2k/movie/{item["id"]}'
        xbmcplugin.addDirectoryItem(plugin.handle, route, xbmcgui.ListItem(title), isFolder=True)
        
    xbmcplugin.endOfDirectory(plugin.handle)

if __name__ == '__main__':
    plugin.run()
