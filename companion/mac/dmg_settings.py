# Layout of the orch Companion disk image (ORCH-1497): the app on the left, an arrow, the Applications folder on
# the right, the way Mac apps are usually installed. Read by dmgbuild (hash-pinned in dmg-requirements.txt); dmgbuild writes the
# window layout itself, so no Finder automation is needed. dmg.sh passes app=<path to orch Companion.app> and background=<tiff>.
import os.path

application = defines["app"]  # noqa: F821  (dmgbuild provides `defines`)
appname = os.path.basename(application)

format = "UDZO"
filesystem = "HFS+"
files = [application]
symlinks = {"Applications": "/Applications"}
hide_extension = [appname]
icon_locations = {appname: (150, 190), "Applications": (450, 190)}

background = defines["background"]  # noqa: F821  (dmg-background.png + @2x as one tiff, made by dmg.sh)
window_rect = ((200, 200), (600, 380))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
show_icon_preview = False
icon_size = 128
text_size = 13
arrange_by = None
