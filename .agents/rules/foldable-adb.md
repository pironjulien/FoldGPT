# Captures authentiques du Fold

- Identifier l’écran Android voulu avant la capture : un appareil pliable expose plusieurs affichages.
- Conserver les octets PNG sans conversion en texte. Utiliser `screencap -p -d DISPLAY_ID` et récupérer stdout en mode binaire ; éviter la redirection PowerShell des données binaires.
- Si une capture temporaire est créée sur le téléphone, la rapatrier puis supprimer uniquement ce fichier temporaire.
- Vérifier la signature PNG et le décodage du fichier avant inspection.
- Garder les originaux et leur provenance dans un dossier privé du projet. Ne publier que les copies dont les informations personnelles ont été vérifiées et anonymisées avec l’accord de Julien.
