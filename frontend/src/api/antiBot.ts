/**
 * Résolution de l'épreuve anti-automatisation, côté navigateur.
 *
 * Le serveur pose une énigme dont la solution ne s'obtient qu'en essayant les nombres
 * un par un : « quel entier, concaténé à ce sel, donne cette empreinte SHA-256 ? ».
 * Voir `backend/app/securite/anti_bot.py` pour le raisonnement et les garanties.
 *
 * ## Aucune dépendance
 *
 * Le calcul utilise `crypto.subtle`, présent dans tous les navigateurs courants : ni
 * bibliothèque, ni script de CDN, ni service tiers contacté. C'est le même parti pris
 * que pour les icônes du graphe et les modules d'enrichissement — un outil
 * d'investigation ne doit pas faire fuiter ses visiteurs vers un tiers.
 *
 * ## Le format
 *
 * Celui d'Altcha (projet libre), afin de pouvoir basculer plus tard sur son composant
 * officiel sans toucher au serveur.
 *
 * ## Pourquoi l'utilisateur n'attend pas
 *
 * L'épreuve est demandée et résolue **dès l'ouverture du formulaire**, en arrière-plan.
 * Le temps que l'analyste saisisse son adresse et son mot de passe, la preuve est
 * prête. Il ne voit donc rien — c'est l'intérêt de ce mécanisme par rapport à une
 * énigme visuelle.
 */

import { appelerApi } from "./client";

export interface DefiAntiBot {
  algorithm: string;
  challenge: string;
  salt: string;
  signature: string;
  maxnumber: number;
}

/** `crypto.subtle` n'est exposé que sur une origine sûre (HTTPS ou localhost). */
export function resolutionPossible(): boolean {
  return typeof crypto !== "undefined" && typeof crypto.subtle !== "undefined";
}

export function demanderDefi(): Promise<DefiAntiBot> {
  return appelerApi<DefiAntiBot>("/auth/defi-anti-robot");
}

const encodeur = new TextEncoder();

async function empreinte(texte: string): Promise<string> {
  const octets = await crypto.subtle.digest("SHA-256", encodeur.encode(texte));
  return Array.from(new Uint8Array(octets))
    .map((o) => o.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Cherche le nombre solution, puis rend la preuve encodée à envoyer au serveur.
 *
 * La boucle rend la main au navigateur périodiquement (`setTimeout` à 0) : sans cela,
 * quelques dizaines de milliers de hachages figeraient brièvement l'interface, ce qui
 * se verrait sur une machine modeste. Un Web Worker serait plus élégant, mais
 * demanderait un fichier séparé pour un gain imperceptible à cette échelle.
 */
export async function resoudreDefi(defi: DefiAntiBot): Promise<string> {
  if (defi.algorithm !== "SHA-256") {
    throw new Error(`Épreuve de type inattendu : ${defi.algorithm}`);
  }

  const PAS = 2000; // hachages entre deux pauses
  for (let nombre = 0; nombre <= defi.maxnumber; nombre++) {
    if (nombre > 0 && nombre % PAS === 0) {
      await new Promise((suite) => setTimeout(suite, 0));
    }
    if ((await empreinte(`${defi.salt}${nombre}`)) === defi.challenge) {
      return btoa(
        JSON.stringify({
          algorithm: defi.algorithm,
          challenge: defi.challenge,
          number: nombre,
          salt: defi.salt,
          signature: defi.signature,
        }),
      );
    }
  }
  // Ne devrait jamais arriver : le serveur tire le nombre dans la plage annoncée.
  throw new Error("Épreuve non résolue : aucune solution dans la plage annoncée.");
}

/** Demande une épreuve et la résout. Rend la preuve prête à joindre à l'inscription. */
export async function obtenirPreuve(): Promise<string> {
  return resoudreDefi(await demanderDefi());
}
