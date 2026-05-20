import sys
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import routing

from resources.lib.sites import sto, aniworld
from resources.lib.utils import resolve_and_play

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
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(sto_index), xbmcgui.ListItem('SerienStream (s.to)'), isFolder=True)
    xbmcplugin.addDirectoryItem(plugin.handle, plugin.url_for(aniworld_index), xbmcgui.ListItem('AniWorld (aniworld.to)'), isFolder=True)
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

if __name__ == '__main__':
    plugin.run()
