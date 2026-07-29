/**
 * Client HTTP de l'API.
 *
 * L'authentification repose sur des cookies httpOnly posés par le backend :
 * `credentials: "include"` est donc indispensable sur chaque appel, et aucun
 * jeton n'est stocké côté JavaScript (protection contre le vol par XSS).
 */

const BASE = "/api/v1";

/** Message unique pour tous les cas « le backend ne répond pas ». */
export const MESSAGE_SERVEUR_INJOIGNABLE =
  "Le serveur ne répond pas. Vérifiez qu'il est bien démarré, puis réessayez.";

/** Erreur d'API portant le code HTTP et le code métier renvoyé par le backend. */
export class ErreurApi extends Error {
  constructor(
    message: string,
    public readonly statut: number,
    public readonly code?: string,
    public readonly detail?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ErreurApi";
  }

  /** Quota mensuel atteint : l'interface propose alors la montée en gamme. */
  get estQuotaDepasse(): boolean {
    return this.statut === 429 || this.code === "quota_depasse";
  }

  /** Fonctionnalité absente du plan actif. */
  get estFonctionnaliteIndisponible(): boolean {
    return this.code === "fonctionnalite_indisponible";
  }

  get estNonAuthentifie(): boolean {
    return this.statut === 401;
  }

  /** Le backend n'a pas répondu : il est arrêté, ou injoignable depuis le navigateur. */
  get estServeurInjoignable(): boolean {
    return this.code === "serveur_injoignable";
  }
}

interface OptionsRequete {
  methode?: "GET" | "POST" | "PATCH" | "DELETE";
  corps?: unknown;
  parametres?: Record<string, string | number | boolean | undefined | null>;
  organisationId?: string | null;
}

function construireUrl(
  chemin: string,
  parametres?: OptionsRequete["parametres"],
): string {
  const url = new URL(`${BASE}${chemin}`, window.location.origin);
  if (parametres) {
    for (const [cle, valeur] of Object.entries(parametres)) {
      if (valeur !== undefined && valeur !== null && valeur !== "") {
        url.searchParams.set(cle, String(valeur));
      }
    }
  }
  return url.pathname + url.search;
}

/**
 * Renouvellement du jeton d'accès.
 *
 * Le jeton d'accès ne vit que 15 minutes, alors qu'une recherche en dure jusqu'à 10 :
 * sans ce mécanisme, l'analyste serait déconnecté en pleine investigation. Le cookie
 * de rafraîchissement, lui, est valable deux semaines.
 *
 * La promesse est partagée entre tous les appels : si dix requêtes reçoivent un 401
 * en même temps, un seul rafraîchissement est déclenché — sinon la rotation des
 * jetons côté serveur invaliderait les tentatives concurrentes.
 */
let rafraichissementEnCours: Promise<boolean> | null = null;

export async function rafraichirSession(): Promise<boolean> {
  if (!rafraichissementEnCours) {
    rafraichissementEnCours = fetch(`${BASE}/auth/rafraichir`, {
      method: "POST",
      credentials: "include",
    })
      .then((reponse) => reponse.ok)
      .catch(() => false)
      .finally(() => {
        // Libère le verrou au tour suivant, une fois les appelants servis
        setTimeout(() => {
          rafraichissementEnCours = null;
        }, 0);
      });
  }
  return rafraichissementEnCours;
}

export async function appelerApi<T>(
  chemin: string,
  options: OptionsRequete = {},
): Promise<T> {
  return executerRequete<T>(chemin, options, true);
}

async function executerRequete<T>(
  chemin: string,
  options: OptionsRequete,
  autoriserRafraichissement: boolean,
): Promise<T> {
  const { methode = "GET", corps, parametres, organisationId } = options;

  const entetes: Record<string, string> = {};
  if (corps !== undefined) {
    entetes["Content-Type"] = "application/json";
  }
  // Permet à un utilisateur membre de plusieurs organisations de choisir laquelle
  // consulter. Le backend revérifie toujours l'appartenance en base.
  if (organisationId) {
    entetes["X-Organisation"] = organisationId;
  }

  let reponse: Response;
  try {
    reponse = await fetch(construireUrl(chemin, parametres), {
      method: methode,
      headers: entetes,
      body: corps !== undefined ? JSON.stringify(corps) : undefined,
      credentials: "include",
    });
  } catch {
    // Échec réseau avant même d'obtenir une réponse : serveur éteint, coupure réseau.
    throw new ErreurApi(MESSAGE_SERVEUR_INJOIGNABLE, 0, "serveur_injoignable");
  }

  // Jeton d'accès expiré : on le renouvelle et on rejoue la requête, une seule fois.
  // Les routes d'authentification elles-mêmes sont exclues, sous peine de boucle.
  if (
    reponse.status === 401 &&
    autoriserRafraichissement &&
    !chemin.startsWith("/auth/rafraichir") &&
    !chemin.startsWith("/auth/connexion") &&
    !chemin.startsWith("/auth/inscription")
  ) {
    if (await rafraichirSession()) {
      return executerRequete<T>(chemin, options, false);
    }
  }

  if (reponse.status === 204) {
    return undefined as T;
  }

  const typeContenu = reponse.headers.get("content-type") || "";
  const estJson = typeContenu.includes("application/json");
  const contenu = estJson ? await reponse.json().catch(() => null) : await reponse.text();

  if (!reponse.ok) {
    const donnees = (estJson ? contenu : null) as Record<string, unknown> | null;

    // Une erreur 5xx sans corps JSON ne vient pas de l'application : c'est le
    // serveur de développement (ou le reverse proxy) qui n'a pas pu joindre l'API.
    // Le distinguer évite d'afficher « erreur 500 » à quelqu'un dont le backend
    // n'est simplement pas démarré.
    if (reponse.status >= 500 && !donnees) {
      throw new ErreurApi(MESSAGE_SERVEUR_INJOIGNABLE, reponse.status, "serveur_injoignable");
    }

    const message =
      (typeof donnees?.detail === "string" && donnees.detail) ||
      messageParDefaut(reponse.status);
    throw new ErreurApi(
      message,
      reponse.status,
      typeof donnees?.code === "string" ? donnees.code : undefined,
      donnees ?? undefined,
    );
  }

  return contenu as T;
}

function messageParDefaut(statut: number): string {
  switch (statut) {
    case 401:
      return "Session expirée, veuillez vous reconnecter.";
    case 403:
      return "Action non autorisée avec votre plan ou votre rôle.";
    case 404:
      return "Ressource introuvable.";
    case 409:
      return "Cette action entre en conflit avec l'état actuel.";
    case 429:
      return "Limite atteinte. Consultez votre page Abonnement.";
    case 503:
      return "Service momentanément indisponible. Réessayez dans un instant.";
    default:
      return `Une erreur est survenue (code ${statut}).`;
  }
}

/** Télécharge un export en déclenchant l'enregistrement du fichier par le navigateur. */
export async function telechargerExport(
  investigationId: string,
  format: "json" | "csv",
  organisationId?: string | null,
): Promise<void> {
  const entetes: Record<string, string> = {};
  if (organisationId) entetes["X-Organisation"] = organisationId;

  const url = `${BASE}/investigations/${investigationId}/export?format=${format}`;
  let reponse = await fetch(url, { credentials: "include", headers: entetes });

  // Même logique que les autres appels : un jeton expiré ne doit pas faire échouer
  // un export que l'utilisateur vient de demander.
  if (reponse.status === 401 && (await rafraichirSession())) {
    reponse = await fetch(url, { credentials: "include", headers: entetes });
  }

  if (!reponse.ok) {
    const donnees = await reponse.json().catch(() => null);
    throw new ErreurApi(
      donnees?.detail || messageParDefaut(reponse.status),
      reponse.status,
      donnees?.code,
    );
  }

  const blob = await reponse.blob();
  const entete = reponse.headers.get("content-disposition") || "";
  const correspondance = entete.match(/filename="?([^"]+)"?/);
  const nomFichier = correspondance?.[1] ?? `export.${format}`;

  const urlBlob = URL.createObjectURL(blob);
  const lien = document.createElement("a");
  lien.href = urlBlob;
  lien.download = nomFichier;
  document.body.appendChild(lien);
  lien.click();
  lien.remove();
  URL.revokeObjectURL(urlBlob);
}
