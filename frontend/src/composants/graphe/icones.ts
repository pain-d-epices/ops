/**
 * Icônes des nœuds du graphe, dans l'esprit des outils d'analyse de liens
 * (Maltego et équivalents) : une silhouette pour une personne, une enveloppe pour
 * une adresse, une épingle pour un lieu.
 *
 * Deux sources d'icônes :
 *
 *  - **Types d'information** : pictogrammes SVG écrits ici et embarqués en data URI.
 *    Aucun fichier à charger, aucune requête réseau, aucune dépendance : le graphe
 *    s'affiche identiquement hors ligne.
 *
 *  - **Comptes** : favicon du site concerné, récupéré auprès de DuckDuckGo.
 *    Reconnaître GitHub ou Reddit d'un coup d'œil vaut mieux qu'un rond de couleur.
 *    Voir `urlFavicon` pour la contrepartie de ce choix.
 */

import type { TypeNoeud } from "../../api/types";

/** Encapsule un tracé SVG en data URI utilisable comme image de fond Cytoscape. */
function icone(traces: string, couleur = "#ffffff"): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ` +
    `fill="none" stroke="${couleur}" stroke-width="2" stroke-linecap="round" ` +
    `stroke-linejoin="round">${traces}</svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

/** Pictogramme par type de nœud. Les comptes utilisent le favicon du site. */
export const ICONES_TYPE: Partial<Record<TypeNoeud, string>> = {
  // Silhouette : le pseudonyme recherché, point de départ de l'investigation
  pseudo: icone(
    '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a8 8 0 0 1 16 0v1"/>',
  ),
  // Deux silhouettes : un autre pseudonyme, possiblement la même personne
  pseudo_alt: icone(
    '<circle cx="9" cy="8" r="3.2"/><path d="M2 20v-.5a7 7 0 0 1 14 0v.5"/>' +
      '<path d="M17 11.5a3 3 0 1 0-2-5.3"/><path d="M18 20v-.5a6 6 0 0 0-2-4.4"/>',
  ),
  // Enveloppe : adresse électronique
  email: icone(
    '<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  ),
  // Carte d'identité : nom réel ou nom affiché
  nom: icone(
    '<rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="8.5" cy="11" r="2.2"/>' +
      '<path d="M5 16.5c.8-1.6 2-2.4 3.5-2.4s2.7.8 3.5 2.4"/><path d="M15 10h4M15 14h4"/>',
  ),
  // Épingle de carte : localisation déclarée
  localisation: icone(
    '<path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  ),
  // Maillons de chaîne : lien externe
  lien: icone(
    '<path d="M10 13a5 5 0 0 0 7.1.1l2.5-2.5a5 5 0 0 0-7.1-7.1L11 5"/>' +
      '<path d="M14 11a5 5 0 0 0-7.1-.1l-2.5 2.5a5 5 0 0 0 7.1 7.1L13 19"/>',
  ),
  // Combiné : numéro de téléphone
  telephone: icone(
    '<path d="M6 3h3l2 5-2.5 1.5a12 12 0 0 0 6 6L16 13l5 2v3a2 2 0 0 1-2.2 2A17 17 0 0 1 4 5.2 2 2 0 0 1 6 3z"/>',
  ),
  // Immeuble : entreprise déclarée
  entreprise: icone(
    '<rect x="4" y="3" width="12" height="18" rx="1"/><path d="M16 8h4v13h-4"/>' +
      '<path d="M8 7h2M8 11h2M8 15h2M12 7h.01M12 11h.01M12 15h.01"/>',
  ),
  // Cadre photo : empreinte d'avatar
  avatar: icone(
    '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/>' +
      '<path d="m4 18 5-4.5 3.5 3 3-2.5L20 18"/>',
  ),
};

/**
 * Adresse du favicon d'un site.
 *
 * Passe par DuckDuckGo plutôt que par Google : le service rend le même
 * service sans alimenter un profil publicitaire. Il faut néanmoins avoir
 * conscience du compromis — interroger un tiers pour chaque domaine trouvé lui
 * révèle, en creux, les sites qui apparaissent dans une investigation. Pour un
 * déploiement où cela poserait problème, il suffit de renvoyer `null` ici : le
 * graphe retombe alors sur les pastilles colorées, sans aucune requête externe.
 */
export function urlFavicon(libelle: string): string | null {
  try {
    const url = new URL(libelle.includes("://") ? libelle : `https://${libelle}`);
    const domaine = url.hostname.toLowerCase();
    if (!domaine || !domaine.includes(".")) return null;
    return `https://icons.duckduckgo.com/ip3/${domaine}.ico`;
  } catch {
    return null;
  }
}
