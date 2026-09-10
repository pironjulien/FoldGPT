# Captures d'Écran ADB & Intégrité Médias (Galaxy Z Fold)

## Règle Absolue : Captures ADB sur Appareils Pliables
Sur les terminaux multi-écrans (comme le Galaxy Z Fold), la commande Android `screencap` détecte plusieurs affichages et émet un avertissement textuel ASCII (`[Warning] Multiple displays were found...`) sur `stdout`.
- **INTERDIT** : Ne JAMAIS rediriger le flux brut de `screencap` sous PowerShell/CMD (`adb exec-out screencap -p > file.png`). Cela injecte l'avertissement ASCII au début du fichier et corrompt le PNG dès son premier octet.
- **OBLIGATOIRE** : TOUJOURS capturer sur le stockage de l'appareil puis rapatrier le fichier avec `adb pull` :
  ```powershell
  adb shell screencap -p /sdcard/screen.png
  adb pull /sdcard/screen.png <destination>.png
  adb shell rm /sdcard/screen.png
  ```

## Garde-Fou : Intégrité des Fichiers avant `view_file`
Avant d'appeler `view_file` sur toute image générée ou capturée :
- Vérifier systématiquement que le fichier est valide (présence de la signature binaire PNG `\x89PNG` ou validation de son format).
- L'envoi d'une image invalide à l'API Gemini provoque une erreur fatale `HTTP 400 Bad Request (INVALID_ARGUMENT)` qui corrompt définitivement l'historique de la session.
