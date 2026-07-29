"""Module d'enrichissement Pixelfed.

Réseau de partage de photos fédéré (protocole ActivityPub). Pixelfed expose
volontairement une API compatible avec celle de Mastodon, afin que les applications
clientes existantes (Tusky, etc.) fonctionnent sans adaptation : le module réutilise
donc directement la logique d'extraction de `ModuleMastodon`.
"""

from __future__ import annotations

from app.modules.mastodon import ModuleMastodon


class ModulePixelfed(ModuleMastodon):
    nom = "pixelfed"
    libelle = "Pixelfed"
    # Instances les plus fréquentées ; une instance absente de cette liste n'est
    # simplement pas enrichie (mais reste trouvée par la recherche large).
    domaines = ["pixelfed.social", "pixelfed.de", "pixey.org", "pixelfed.uno"]
