/**
 * Client HTTP de l'API.
 *
 * L'authentification repose sur des cookies httpOnly posés par le backend :
 * `credentials: "include"` est donc indispensable sur chaque appel, et aucun
 * jeton n'est stocké côté JavaScript (protection contre le vol par XSS).
 */

const BASE = "/api/v1";

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

export async function appelerApi<T>(
  chemin: string,
  options: OptionsRequete = {},
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

  const reponse = await fetch(construireUrl(chemin, parametres), {
    method: methode,
    headers: entetes,
    body: corps !== undefined ? JSON.stringify(corps) : undefined,
    credentials: "include",
  });

  if (reponse.status === 204) {
    return undefined as T;
  }

  const typeContenu = reponse.headers.get("content-type") || "";
  const estJson = typeContenu.includes("application/json");
  const contenu = estJson ? await reponse.json().catch(() => null) : await reponse.text();

  if (!reponse.ok) {
    const donnees = (estJson ? contenu : null) as Record<string, unknown> | null;
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

  const reponse = await fetch(
    `${BASE}/investigations/${investigationId}/export?format=${format}`,
    { credentials: "include", headers: entetes },
  );

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

  const url = URL.createObjectURL(blob);
  const lien = document.createElement("a");
  lien.href = url;
  lien.download = nomFichier;
  document.body.appendChild(lien);
  lien.click();
  lien.remove();
  URL.revokeObjectURL(url);
}
