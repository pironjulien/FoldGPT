#!/data/data/com.termux/files/usr/bin/bash

# 1. Configurer Termux:X11 : ergonomie tactile Fold, échelle 2.4, bouton et gestes clavier
am broadcast -a com.termux.x11.CHANGE_PREFERENCE -p com.termux.x11 \
  -e touchMode "Direct touch" \
  -e showAdditionalKbd "true" \
  -e extra_keys_config "[[KEYBOARD]]" \
  -e adjustHeightForEK "true" \
  -e adjustResolution "true" \
  -e fullscreen "true" \
  -e swipeUpAction "toggle soft keyboard" \
  -e backButtonAction "toggle soft keyboard" \
  -e notificationButton0Action "toggle soft keyboard" >/dev/null 2>&1

# 2. Démarrer le serveur X11 sur :1 si non actif
if ! pgrep termux-x11 >/dev/null 2>&1; then
    termux-x11 :1 >/dev/null 2>&1 &
    sleep 1
fi

# 3. Ouvrir Termux:X11 au premier plan
am start --user 0 -n com.termux.x11/com.termux.x11.MainActivity >/dev/null 2>&1

# 4. Tuer d éventuels panneaux parasites
pkill -9 -f xfce4-panel >/dev/null 2>&1 || true

# 5. Démarrer ChatGPT dans Debian PRoot s il ne tourne pas déjà
if ! proot-distro login --user julien fold-debian -- pgrep chatgpt >/dev/null 2>&1; then
    nohup proot-distro login --user julien \
      --bind /data/data/com.termux/files/usr/tmp/.X11-unix:/tmp/.X11-unix \
      --bind /sdcard/Projects:/home/julien/Projects \
      fold-debian -- \
      env DISPLAY=:1 chatgpt --ozone-platform=x11 --force-device-scale-factor=2.4 --remote-debugging-port=9222 >/dev/null 2>&1 &
fi

# 6. Démarrer le démon de clavier automatique (Focus Bridge)
mkdir -p "$HOME/fold-logs"
if ! pgrep -f "foldgpt_keyboard_daemon.py" >/dev/null 2>&1; then
    nohup python3 -u "$HOME/foldgpt_keyboard_daemon.py" > "$HOME/fold-logs/keyboard.log" 2>&1 &
fi

# 7. Ajuster la géométrie plein écran Fold
sleep 2
proot-distro login --user julien \
  --bind /data/data/com.termux/files/usr/tmp/.X11-unix:/tmp/.X11-unix \
  fold-debian -- \
  env DISPLAY=:1 xdotool search --onlyvisible --class chatgpt windowsize 2448 1768 windowmove 0 0 >/dev/null 2>&1 || true
