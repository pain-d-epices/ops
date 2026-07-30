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
 *
 * ---
 *
 * ## Pourquoi toute la géométrie est portée par le SVG
 *
 * Les nœuds n'ont pas tous la même forme (étoile, losange, étiquette, chevron…), et
 * une forme ne remplit pas son cadre : un losange n'occupe que la moitié de la
 * largeur disponible en son milieu. Une icône dimensionnée sur le **cadre** déborde
 * donc de la **forme**.
 *
 * Trois pièges ont été identifiés en mesurant, et sont traités ici :
 *
 * 1. `background-position-x/y` de Cytoscape ne place pas le centre de l'image : le
 *    pourcentage interpole l'espace *libre* autour d'elle (`x += (largeurNœud -
 *    largeurImage) × pourcentage`, voir `drawing-images.mjs`). Avec une icône
 *    occupant 82 % du nœud, demander « 42 % » ne la décale que de 1,4 % — d'où des
 *    corrections de centrage qui semblaient appliquées sans effet visible.
 * 2. Un SVG déclaré avec `viewBox` seul n'a pas de taille intrinsèque : le
 *    navigateur lui attribue 150 × 150 (repli arbitraire, mesuré). Cytoscape lit
 *    cette taille, et le rendu varie alors avec le niveau de zoom.
 * 3. Plusieurs pictogrammes ne sont pas centrés dans leur propre carré d'écriture
 *    (la double silhouette est décalée de 1 unité sur 24 vers la gauche).
 *
 * D'où le parti pris : Cytoscape reçoit une consigne unique et triviale pour tous
 * les types — « dessine cette image sur 100 % du nœud, centrée » — et c'est le SVG
 * qui porte l'échelle et le recentrage, calculés ci-dessous. Aucun pourcentage de
 * position n'est utilisé, et les SVG déclarent leurs dimensions.
 */

import type { TypeNoeud } from "../../api/types";

/** Côté du carré d'écriture des pictogrammes (unités SVG). */
const CANEVAS = 24;

/**
 * Taille de rastérisation demandée au navigateur. Sans dimensions explicites, un
 * SVG n'a pas de taille intrinsèque définie (voir l'en-tête). Une valeur nettement
 * supérieure à la taille d'affichage garde le tracé net au zoom maximal.
 */
const RASTER = 128;

/** Épaisseur de trait visée, dans les unités du canevas. */
const EPAISSEUR_TRAIT = 2;

/**
 * Encre réellement occupée par chaque pictogramme dans son carré de 24, contour et
 * terminaisons arrondies compris, et centre de cette encre.
 *
 * Obtenu en **rastérisant** chaque tracé à 480 px (20 px par unité) et en relevant
 * la boîte des pixels non transparents : c'est la seule mesure fidèle à ce que le
 * navigateur dessinera. `getBBox()` ne conviendrait pas, car il rend la boîte de la
 * géométrie sans le contour ni les terminaisons.
 *
 * Plusieurs pictogrammes ne sont pas centrés dans leur carré (la double silhouette
 * est à 10,97 au lieu de 12) : c'est corrigé par construction ci-dessous.
 *
 * À remesurer si un tracé est modifié — un pictogramme dont l'encre est mal
 * déclarée sera mal dimensionné.
 */
const ENCRE: Record<string, { cote: number; cx: number; cy: number }> = {
  pseudo: { cote: 19, cx: 12, cy: 12.5 },
  pseudo_alt: { cote: 19.95, cx: 10.97, cy: 12.4 },
  email: { cote: 21, cx: 12, cy: 12 },
  nom: { cote: 22, cx: 12, cy: 12 },
  localisation: { cote: 20, cx: 12, cy: 12 },
  lien: { cote: 22, cx: 12, cy: 12 },
  telephone: { cote: 19.05, cx: 12.47, cy: 11.53 },
  entreprise: { cote: 20, cx: 12, cy: 12 },
  avatar: { cote: 20, cx: 12, cy: 12 },
};

/**
 * Plus grand carré à côtés parallèles aux axes inscriptible dans chaque forme de
 * nœud, exprimé en fraction de la taille du nœud, avec le décalage de son centre.
 *
 * Calculé numériquement (recherche du centre optimal, puis dichotomie sur le côté)
 * à partir des polygones **réels** de Cytoscape, lus dans
 * `renderer/base/node-shapes.mjs` — pas d'une approximation à l'œil :
 *
 * - `star`   : côté 57 % du nœud, centre 10,4 % plus bas (les branches du bas
 *              laissent moins de place que la pointe du haut)
 * - `tag`    : côté 72,7 %, centre 13,6 % vers la gauche (le corps rectangulaire
 *              est à gauche, la pointe déporte le cadre à droite)
 * - `vee`    : côté 33 % seulement — un chevron est très creux
 * - `diamond`, `rhomboid` : 50 %, la moitié du cadre, résultat exact et connu
 * - `ellipse` : 70,7 % (= 1/√2), le carré inscrit dans un cercle
 *
 * Les formes arrondies (`round-rectangle`, `barrel`) sont approchées par leur
 * rectangle, légèrement rentré pour tenir compte des congés.
 */
const CARRE_INSCRIT: Record<string, { cote: number; dx: number; dy: number }> = {
  star: { cote: 0.57, dx: -0.0128, dy: 0.1042 },
  ellipse: { cote: 0.707, dx: 0, dy: 0 },
  diamond: { cote: 0.5, dx: 0, dy: 0 },
  tag: { cote: 0.727, dx: -0.1363, dy: 0 },
  hexagon: { cote: 0.667, dx: 0, dy: 0 },
  octagon: { cote: 0.707, dx: 0, dy: 0 },
  vee: { cote: 0.333, dx: 0, dy: 0 },
  rhomboid: { cote: 0.5, dx: 0, dy: 0 },
  "round-rectangle": { cote: 0.94, dx: 0, dy: 0 },
  barrel: { cote: 0.94, dx: 0, dy: -0.025 },
};

/** Repli si une forme n'est pas décrite ci-dessus : le carré inscrit dans un cercle. */
const CARRE_PAR_DEFAUT = { cote: 0.707, dx: 0, dy: 0 };

/** Tracés SVG, écrits dans un carré de 24 unités. */
const TRACES: Record<string, string> = {
  // Silhouette : le pseudonyme recherché, point de départ de l'investigation
  pseudo: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a8 8 0 0 1 16 0v1"/>',
  // Deux silhouettes : un autre pseudonyme, possiblement la même personne
  pseudo_alt:
    '<circle cx="9" cy="8" r="3.2"/><path d="M2 20v-.5a7 7 0 0 1 14 0v.5"/>' +
    '<path d="M17 11.5a3 3 0 1 0-2-5.3"/><path d="M18 20v-.5a6 6 0 0 0-2-4.4"/>',
  // Enveloppe : adresse électronique
  email: '<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  // Carte d'identité : nom réel ou nom affiché
  nom:
    '<rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="8.5" cy="11" r="2.2"/>' +
    '<path d="M5 16.5c.8-1.6 2-2.4 3.5-2.4s2.7.8 3.5 2.4"/><path d="M15 10h4M15 14h4"/>',
  // Épingle de carte : localisation déclarée
  localisation:
    '<path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  // Maillons de chaîne : lien externe
  lien:
    '<path d="M10 13a5 5 0 0 0 7.1.1l2.5-2.5a5 5 0 0 0-7.1-7.1L11 5"/>' +
    '<path d="M14 11a5 5 0 0 0-7.1-.1l-2.5 2.5a5 5 0 0 0 7.1 7.1L13 19"/>',
  // Combiné : numéro de téléphone
  telephone:
    '<path d="M6 3h3l2 5-2.5 1.5a12 12 0 0 0 6 6L16 13l5 2v3a2 2 0 0 1-2.2 2A17 17 0 0 1 4 5.2 2 2 0 0 1 6 3z"/>',
  // Immeuble : entreprise déclarée
  entreprise:
    '<rect x="4" y="3" width="12" height="18" rx="1"/><path d="M16 8h4v13h-4"/>' +
    '<path d="M8 7h2M8 11h2M8 15h2M12 7h.01M12 11h.01M12 15h.01"/>',
  // Cadre photo : empreinte d'avatar
  avatar:
    '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/>' +
    '<path d="m4 18 5-4.5 3.5 3 3-2.5L20 18"/>',
};

/** Arrondi court : une data URI plus légère, sans perte visible. */
const arr = (valeur: number) => Number(valeur.toFixed(4));

/**
 * Fabrique une icône dont l'encre occupe `cible.cote` du nœud et dont le centre est
 * décalé de `cible.dx`/`cible.dy` (fractions de la taille du nœud).
 *
 * L'épaisseur de trait est divisée par l'échelle appliquée, de sorte que toutes les
 * icônes conservent le même poids de trait à l'écran quelle que soit leur taille —
 * sans quoi l'icône du chevron (33 %) aurait un trait deux fois plus fin que celle
 * du rectangle arrondi (94 %).
 */
function construire(
  traces: string,
  encre: { cote: number; cx: number; cy: number },
  cible: { cote: number; dx: number; dy: number },
  couleur: string,
): string {
  // L'encre visible vaut « géométrie mise à l'échelle + une épaisseur de trait »,
  // le trait n'étant justement pas mis à l'échelle (voir plus haut). L'échelle se
  // déduit donc en retirant le trait des deux côtés de l'égalité, sans quoi les
  // icônes les plus réduites dépassent leur cible de plusieurs points — mesuré :
  // le chevron sortait à 39 % du nœud au lieu des 33 % voulus.
  const encreUtile = encre.cote - EPAISSEUR_TRAIT;
  const cibleUtile = CANEVAS * cible.cote - EPAISSEUR_TRAIT;
  const echelle = cibleUtile / encreUtile;
  const tx = CANEVAS / 2 + CANEVAS * cible.dx - echelle * encre.cx;
  const ty = CANEVAS / 2 + CANEVAS * cible.dy - echelle * encre.cy;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${RASTER}" height="${RASTER}" ` +
    `viewBox="0 0 ${CANEVAS} ${CANEVAS}">` +
    `<g transform="translate(${arr(tx)} ${arr(ty)}) scale(${arr(echelle)})" ` +
    `fill="none" stroke="${couleur}" stroke-width="${arr(EPAISSEUR_TRAIT / echelle)}" ` +
    `stroke-linecap="round" stroke-linejoin="round">${traces}</g></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

/**
 * Icône d'un type de nœud, ajustée à la forme qu'il porte dans le graphe.
 *
 * À utiliser avec `background-width` et `background-height` à 100 % et sans
 * `background-position` : l'ajustement est déjà dans l'image.
 */
export function iconePourForme(
  type: TypeNoeud,
  forme: string,
  couleur = "#ffffff",
): string | null {
  const traces = TRACES[type];
  const encre = ENCRE[type];
  if (!traces || !encre) return null;
  return construire(traces, encre, CARRE_INSCRIT[forme] ?? CARRE_PAR_DEFAUT, couleur);
}

/** Fraction du nœud utilisable par une image, pour une forme donnée. */
export function coteUtile(forme: string): number {
  return (CARRE_INSCRIT[forme] ?? CARRE_PAR_DEFAUT).cote;
}

/**
 * Pictogramme centré et à taille pleine, pour la légende et les listes — hors
 * graphe, il n'y a aucune forme à laquelle s'ajuster.
 */
export const ICONES_TYPE: Partial<Record<TypeNoeud, string>> = Object.fromEntries(
  Object.keys(TRACES).map((type) => [
    type,
    construire(TRACES[type], ENCRE[type], { cote: 0.92, dx: 0, dy: 0 }, "#ffffff"),
  ]),
) as Partial<Record<TypeNoeud, string>>;

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
