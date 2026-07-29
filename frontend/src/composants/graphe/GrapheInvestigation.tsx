/**
 * Graphe interactif de l'investigation (Cytoscape).
 *
 * Deux exigences ont guidé l'implémentation :
 *
 *  - **Mise à jour différentielle.** Pendant une recherche, de nouveaux nœuds
 *    arrivent en continu. Reconstruire le graphe à chaque fois relancerait la
 *    disposition et ferait sauter tous les nœuds : l'analyste perdrait ses repères
 *    en plein travail. Seuls les éléments réellement nouveaux sont donc ajoutés,
 *    et la disposition n'est recalculée que pour eux.
 *
 *  - **Le score se lit d'un coup d'œil.** Couleur et taille des comptes traduisent
 *    directement le niveau de confiance, avec le même code couleur que les tableaux.
 */

import cytoscape, {
  type Core,
  type ElementDefinition,
  type NodeSingular,
} from "cytoscape";
import fcose from "cytoscape-fcose";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Graphe, TypeNoeud } from "../../api/types";

cytoscape.use(fcose);

const COULEURS_NOEUD: Record<TypeNoeud, string> = {
  pseudo: "#a371f7",
  compte: "#4c8bf5",
  email: "#db6d28",
  pseudo_alt: "#bc8cff",
  nom: "#f0883e",
  localisation: "#2ea043",
  lien: "#58a6ff",
  avatar: "#8b949e",
  telephone: "#e3b341",
  entreprise: "#6e7681",
};

const LIBELLES_TYPE: Record<TypeNoeud, string> = {
  pseudo: "Pseudonyme recherché",
  compte: "Compte trouvé",
  email: "Adresse e-mail",
  pseudo_alt: "Autre pseudonyme",
  nom: "Nom",
  localisation: "Localisation",
  lien: "Lien externe",
  avatar: "Avatar",
  telephone: "Téléphone",
  entreprise: "Entreprise",
};

/**
 * Forme géométrique par type de nœud.
 *
 * La couleur seule ne suffit pas à distinguer une dizaine de catégories : elle se
 * confond vite sur un graphe dense, et reste inaccessible aux daltoniens. La forme
 * donne un second signal, lisible même en petit et en noir et blanc.
 */
type FormeNoeud = cytoscape.Css.NodeShape;

const FORMES_NOEUD: Record<TypeNoeud, FormeNoeud> = {
  pseudo: "star",              // le point de départ de l'investigation
  compte: "ellipse",           // le plus fréquent : forme neutre
  email: "diamond",            // information forte, très identifiante
  pseudo_alt: "tag",           // mène à une nouvelle recherche
  nom: "hexagon",
  localisation: "round-rectangle",
  lien: "vee",
  avatar: "octagon",
  telephone: "rhomboid",
  entreprise: "barrel",
};

/** Couleur d'un compte selon son score : même code que les badges des tableaux. */
function couleurScore(score: number): string {
  if (score >= 70) return "#3fb950";
  if (score >= 40) return "#d29922";
  return "#8b949e";
}

function tailleNoeud(type: TypeNoeud, score: number): number {
  if (type === "pseudo") return 52;
  if (type === "compte") return 24 + (score / 100) * 22; // 24 à 46 px selon le score
  return 22;
}

/**
 * Paramètres de disposition adaptés à la densité du graphe.
 *
 * Une investigation peut produire cinq nœuds comme deux cents. Des valeurs fixes
 * donnent soit un graphe perdu dans le vide, soit — bien plus gênant — une pelote
 * illisible. L'espacement croît donc avec le nombre de nœuds.
 */
function parametresDisposition(nombreNoeuds: number) {
  const facteur = Math.min(3, Math.max(1, Math.sqrt(nombreNoeuds / 25)));
  return {
    nodeSeparation: Math.round(90 * facteur),
    idealEdgeLength: Math.round(95 * facteur),
    nodeRepulsion: Math.round(6500 * facteur * 1.6),
    gravity: nombreNoeuds > 80 ? 0.15 : 0.25, // moins de gravité = moins d'agglutination
  };
}

interface Proprietes {
  graphe: Graphe | undefined;
  noeudSelectionne: string | null;
  onSelectionner: (noeudId: string | null, profilId: string | null) => void;
  scoreMinimal: number;
  onScoreMinimalChange: (valeur: number) => void;
  typesMasques: Set<string>;
  onBasculerType: (type: string) => void;
}

export function GrapheInvestigation({
  graphe,
  noeudSelectionne,
  onSelectionner,
  scoreMinimal,
  onScoreMinimalChange,
  typesMasques,
  onBasculerType,
}: Proprietes) {
  const conteneur = useRef<HTMLDivElement>(null);
  const instance = useRef<Core | null>(null);
  const identifiantsConnus = useRef<Set<string>>(new Set());
  const [pret, setPret] = useState(false);

  const typesPresents = useMemo(() => {
    const types = new Set<string>();
    graphe?.noeuds.forEach((noeud) => types.add(noeud.type));
    return Array.from(types).sort();
  }, [graphe]);

  // --- Création de l'instance -----------------------------------------------
  useEffect(() => {
    if (!conteneur.current || instance.current) return;

    const cy = cytoscape({
      container: conteneur.current,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(couleur)",
            width: "data(taille)",
            height: "data(taille)",
            label: "data(libelleCourt)",
            color: "#e6edf3",
            "font-size": "10px",
            "text-valign": "bottom",
            "text-margin-y": 6,
            "text-wrap": "ellipsis",
            "text-max-width": "110px",
            // Contour sombre autour du texte : le libellé reste lisible même
            // lorsqu'il chevauche une arête ou un autre nœud.
            "text-outline-color": "#0f1216",
            "text-outline-width": 2,
            "border-width": 2,
            "border-color": "data(couleurBordure)",
            "transition-property": "border-width, border-color",
            "transition-duration": 120,
          },
        },
        // Une règle par type : la forme ne peut pas être pilotée par `data()`,
        // Cytoscape n'acceptant qu'une valeur littérale pour cette propriété.
        ...Object.entries(FORMES_NOEUD).map(([type, forme]) => ({
          selector: `node[type="${type}"]`,
          style: { shape: forme },
        })),
        {
          selector: "node.selectionne",
          style: {
            "border-width": 4,
            "border-color": "#ffffff",
            "z-index": 100,
          },
        },
        {
          // Un profil marqué faux positif reste visible mais nettement estompé :
          // le masquer ferait perdre la trace du travail de vérification déjà fait.
          selector: "node.rejete",
          style: { opacity: 0.3, "border-style": "dashed" },
        },
        {
          selector: "edge",
          style: {
            width: "data(epaisseur)",
            "line-color": "#3d444d",
            "target-arrow-color": "#3d444d",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.8,
            "curve-style": "bezier",
            opacity: 0.65,
          },
        },
        {
          selector: "edge.pivot",
          style: { "line-color": "#a371f7", "target-arrow-color": "#a371f7", "line-style": "dashed" },
        },
        {
          selector: "edge.voisine",
          style: { "line-color": "#4c8bf5", "target-arrow-color": "#4c8bf5", opacity: 1, width: 3 },
        },
      ],
      layout: { name: "preset" },
      minZoom: 0.15,
      maxZoom: 3,
      wheelSensitivity: 0.25,
      boxSelectionEnabled: false,
    });

    cy.on("tap", "node", (evenement) => {
      const noeud = evenement.target as NodeSingular;
      onSelectionner(noeud.id(), (noeud.data("profilId") as string | null) ?? null);
    });

    // Clic dans le vide : désélection
    cy.on("tap", (evenement) => {
      if (evenement.target === cy) onSelectionner(null, null);
    });

    instance.current = cy;
    setPret(true);

    return () => {
      cy.destroy();
      instance.current = null;
      identifiantsConnus.current = new Set();
    };
    // onSelectionner est stable côté appelant ; on ne recrée jamais l'instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Synchronisation différentielle des données ---------------------------
  useEffect(() => {
    const cy = instance.current;
    if (!cy || !graphe || !pret) return;

    const noeudsVisibles = graphe.noeuds.filter((n) => !typesMasques.has(n.type));
    const identifiantsVisibles = new Set(noeudsVisibles.map((n) => n.id));

    const nouveauxElements: ElementDefinition[] = [];

    for (const noeud of noeudsVisibles) {
      const existant = cy.getElementById(noeud.id);
      const donnees = {
        id: noeud.id,
        type: noeud.type,
        libelle: noeud.libelle,
        libelleCourt: raccourcir(noeud.libelle, noeud.type),
        profilId: noeud.profil_id,
        score: noeud.score,
        couleur:
          noeud.type === "compte"
            ? couleurScore(noeud.score)
            : (COULEURS_NOEUD[noeud.type] ?? "#8b949e"),
        couleurBordure: COULEURS_NOEUD[noeud.type] ?? "#8b949e",
        taille: tailleNoeud(noeud.type, noeud.score),
      };

      if (existant.length > 0) {
        // Nœud déjà présent : on met à jour ses données sans toucher à sa position
        existant.data(donnees);
        existant.toggleClass("rejete", noeud.score === 0 && noeud.type === "compte");
      } else {
        nouveauxElements.push({ group: "nodes", data: donnees });
      }
    }

    for (const arete of graphe.aretes) {
      if (!identifiantsVisibles.has(arete.source) || !identifiantsVisibles.has(arete.cible)) {
        continue;
      }
      if (cy.getElementById(arete.id).length > 0) continue;
      nouveauxElements.push({
        group: "edges",
        data: {
          id: arete.id,
          source: arete.source,
          target: arete.cible,
          type: arete.type,
          libelle: arete.libelle,
          epaisseur: 1 + arete.poids,
        },
        classes: arete.type === "pivot_vers" ? "pivot" : undefined,
      });
    }

    // Retrait des éléments filtrés ou disparus
    cy.nodes().forEach((noeud) => {
      if (!identifiantsVisibles.has(noeud.id())) cy.remove(noeud);
    });

    if (nouveauxElements.length === 0) return;

    const premierRendu = identifiantsConnus.current.size === 0;
    cy.add(nouveauxElements);
    identifiantsVisibles.forEach((id) => identifiantsConnus.current.add(id));

    // Cytoscape mesure son conteneur à la création. Comme le graphe est monté dans
    // un onglet, ses dimensions peuvent avoir changé depuis : sans ce resize, la
    // disposition se calcule sur une surface erronée et tous les nœuds se tassent.
    cy.resize();

    const reglages = parametresDisposition(cy.nodes().length);

    cy.layout({
      name: "fcose",
      // Au premier rendu on soigne la disposition (c'est ce que l'analyste voit en
      // ouvrant le graphe) ; ensuite on privilégie la rapidité pour ne pas figer
      // l'écran à chaque nouveau compte trouvé.
      quality: premierRendu ? "proof" : "default",
      animate: !premierRendu,
      animationDuration: 380,
      // Au premier rendu, on part d'un placement aléatoire : fcose obtient un bien
      // meilleur résultat que depuis des positions initiales toutes identiques.
      randomize: premierRendu,
      ...reglages,
      padding: 50,
      fit: premierRendu,
    } as cytoscape.LayoutOptions).run();
  }, [graphe, typesMasques, pret]);

  // --- Réorganisation à l'ouverture -----------------------------------------
  // Le composant est démonté quand on quitte l'onglet Graphe. À chaque retour, on
  // repart donc d'une disposition propre et ajustée à la taille de la fenêtre,
  // plutôt que d'un amas hérité d'un conteneur qui n'avait pas la bonne dimension.
  useEffect(() => {
    const cy = instance.current;
    if (!cy || !pret) return;

    const ajuster = () => {
      if (!instance.current || instance.current.nodes().length === 0) return;
      instance.current.resize();
      instance.current.fit(instance.current.elements(), 50);
    };

    const minuterie = window.setTimeout(ajuster, 450);
    window.addEventListener("resize", ajuster);
    return () => {
      window.clearTimeout(minuterie);
      window.removeEventListener("resize", ajuster);
    };
  }, [pret]);

  // --- Mise en évidence de la sélection -------------------------------------
  useEffect(() => {
    const cy = instance.current;
    if (!cy) return;

    cy.nodes().removeClass("selectionne");
    cy.edges().removeClass("voisine");

    if (!noeudSelectionne) return;
    const noeud = cy.getElementById(noeudSelectionne);
    if (noeud.length === 0) return;

    noeud.addClass("selectionne");
    noeud.connectedEdges().addClass("voisine");
  }, [noeudSelectionne, graphe]);

  const recentrer = () => {
    instance.current?.animate({ fit: { eles: instance.current.elements(), padding: 40 }, duration: 300 });
  };

  const reorganiser = () => {
    const cy = instance.current;
    if (!cy) return;
    cy.resize();
    cy.layout({
      name: "fcose",
      quality: "proof",
      animate: true,
      animationDuration: 500,
      randomize: true,
      ...parametresDisposition(cy.nodes().length),
      padding: 50,
      fit: true,
    } as cytoscape.LayoutOptions).run();
  };

  return (
    <div className="conteneur-graphe">
      <div className="controles-graphe">
        <div>
          <label htmlFor="filtre-score">
            Score minimal des comptes : {scoreMinimal}
          </label>
          <input
            id="filtre-score"
            type="range"
            min={0}
            max={100}
            step={5}
            value={scoreMinimal}
            onChange={(e) => onScoreMinimalChange(Number(e.target.value))}
          />
        </div>

        {typesPresents.length > 1 && (
          <div>
            <label>Types affichés</label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {typesPresents.map((type) => {
                const masque = typesMasques.has(type);
                return (
                  <button type="button"
                    key={type}
                    className="bouton-petit"
                    style={{
                      opacity: masque ? 0.4 : 1,
                      borderColor: COULEURS_NOEUD[type as TypeNoeud] ?? "var(--bordure)",
                      padding: "2px 8px",
                      fontSize: 11.5,
                    }}
                    onClick={() => onBasculerType(type)}
                    title={masque ? "Afficher" : "Masquer"}
                  >
                    {LIBELLES_TYPE[type as TypeNoeud] ?? type}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="outils-graphe">
        <button type="button" className="bouton-petit" onClick={recentrer} title="Ajuster à l'écran">
          Recentrer
        </button>
        <button type="button" className="bouton-petit" onClick={reorganiser} title="Recalculer la disposition">
          Réorganiser
        </button>
      </div>

      <div ref={conteneur} className="toile-graphe" />

      <div className="legende">
        {/* Couleur = niveau de confiance du compte */}
        <div className="legende-entree">
          <span className="legende-pastille" style={{ background: "#3fb950" }} />
          Confiance élevée
        </div>
        <div className="legende-entree">
          <span className="legende-pastille" style={{ background: "#d29922" }} />
          Moyenne
        </div>
        <div className="legende-entree">
          <span className="legende-pastille" style={{ background: "#8b949e" }} />
          Faible
        </div>

        {/* Forme = nature de l'élément, lisible indépendamment de la couleur */}
        <div className="legende-entree" style={{ width: "100%", marginTop: 4 }}>
          {(
            [
              ["★", "pseudo", "Pseudonyme"],
              ["●", "compte", "Compte"],
              ["◆", "email", "E-mail"],
              ["⬔", "pseudo_alt", "Autre pseudo"],
              ["⬢", "nom", "Nom"],
              ["▭", "localisation", "Lieu"],
              ["∨", "lien", "Lien"],
            ] as const
          ).map(([symbole, type, libelle]) => (
            <span
              key={type}
              style={{ display: "inline-flex", alignItems: "center", gap: 4, marginRight: 12 }}
            >
              <span style={{ color: COULEURS_NOEUD[type as TypeNoeud], fontSize: 13 }}>
                {symbole}
              </span>
              {libelle}
            </span>
          ))}
        </div>

        <div className="legende-entree" style={{ width: "100%", color: "var(--texte-faible)" }}>
          La taille d'un compte reflète son score. Cliquez sur un nœud pour le détail.
        </div>
      </div>
    </div>
  );
}

/** Raccourcit le libellé affiché sous un nœud : une URL entière serait illisible. */
function raccourcir(libelle: string, type: TypeNoeud): string {
  if (type === "compte" || type === "lien") {
    try {
      const url = new URL(libelle.includes("://") ? libelle : `https://${libelle}`);
      const domaine = url.hostname.replace(/^www\./, "");
      const dernierSegment = url.pathname.split("/").filter(Boolean).pop();
      return dernierSegment ? `${domaine}/${dernierSegment}` : domaine;
    } catch {
      // Libellé non analysable comme URL : on retombe sur la troncature simple
    }
  }
  return libelle.length > 28 ? `${libelle.slice(0, 27)}…` : libelle;
}
