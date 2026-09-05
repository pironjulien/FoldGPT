"""Generate the user-authorized keyring secret in NexusSecure and type via stdin."""
import os
import secrets
import subprocess
from pathlib import Path

vault = Path(os.environ['OneDrive']) / 'Documents/NexusSecure/projects/ChatgptFold'
vault.mkdir(parents=True, exist_ok=True)
secret_file = vault / 'linux-keyring-password.txt'
if not secret_file.exists():
    secret_file.write_text(secrets.token_urlsafe(32), encoding='utf-8')
password = secret_file.read_text(encoding='utf-8').strip()
runtime = Path(os.environ['LOCALAPPDATA']) / 'ChatgptFold'
base = ['ssh', '-p', '18022', '-i', str(runtime / 'usb_ed25519'),
        '-o', 'BatchMode=yes', '-o', 'UserKnownHostsFile=' + str(runtime / 'known_hosts'),
        'u0_a409@127.0.0.1']
def run(command, data=None):
    subprocess.run(base + [command], input=data, text=True, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
run('DISPLAY=:1 xdotool windowactivate --sync 0x1c00004')
run('DISPLAY=:1 xdotool key --clearmodifiers ctrl+a')
run('DISPLAY=:1 xdotool type --clearmodifiers --file -', password)
run('DISPLAY=:1 xdotool key Tab')
run('DISPLAY=:1 xdotool type --clearmodifiers --file -', password)
run('DISPLAY=:1 xdotool key Tab Tab Return')
print('Secret saved in NexusSecure; secure keyring form submitted.')
