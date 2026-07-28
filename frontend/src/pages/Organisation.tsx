import { useEffect, useState, type FormEvent } from "react";

import { ErreurApi } from "../api/client";
import {
  useAbonnement,
  useInviter,
  useMembres,
  useModifierOrganisation,
  useModules,
  useOrganisation,
} from "../api/hooks";
import type { ModePivot, RoleMembre } from "../api/types";
import { Chargement, MessageErreur } from "../composants/ui";
import { useAuth } from "../contexts/AuthContext";
import { formaterDate } from "../utilitaires/format";

const LIBELLES_ROLE: Record<RoleMembre, string> = {
  admin: "Administrateur",
  analyste: "Analyste",
  lecteur: "Lecteur",
};

export function PageOrganisation() {
  const { organisation: organisationCourante } = useAuth();
  const { data: organisation, isLoading, error } = useOrganisation();
  const estAdmin = organisationCourante?.role === "admin";

  if (isLoading) return <Chargement />;
  if (error || !organisation) {
    return <MessageErreur>Impossible de charger l'organisation.</MessageErreur>;
  }

  return (
    <div className="pile" style={{ gap: 24 }}>
      <div>
        <h1>{organisation.nom}</h1>
        <p className="attenue">
          Créée le {formaterDate(organisation.cree_le)} · identifiant{" "}
          <span className="mono">{organisation.slug}</span>
        </p>
      </div>

      <PreferencesRebond estAdmin={estAdmin} />
      <ListeMembres estAdmin={estAdmin} />
      <ModulesDisponibles />
    </div>
  );
}

function PreferencesRebond({ estAdmin }: { estAdmin: boolean }) {
  const { data: organisation } = useOrganisation();
  const { data: abonnement } = useAbonnement();
  const modifier = useModifierOrganisation();

  const [modePivot, setModePivot] = useState<ModePivot>("supervise");
  const [profondeur, setProfondeur] = useState(1);
  const [retention, setRetention] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  // Les champs sont initialisés une fois l'organisation chargée
  useEffect(() => {
    if (!organisation) return;
    setModePivot(organisation.mode_pivot);
    setProfondeur(organisation.profondeur_pivot_souhaitee);
    setRetention(organisation.retention_jours);
  }, [organisation]);

  if (!organisation) return null;

  const plan = abonnement?.plan;
  const pivotAutoDisponible = Boolean(plan?.fonctionnalites.includes("pivot_automatique"));
  const profondeurMax = plan?.profondeur_pivot_max ?? 0;

  const bride =
    organisation.mode_pivot !== organisation.mode_pivot_effectif ||
    organisation.profondeur_pivot_souhaitee !== organisation.profondeur_pivot_effective;

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setMessage(null);
    setErreur(null);
    try {
      await modifier.mutateAsync({
        mode_pivot: modePivot,
        profondeur_pivot_souhaitee: profondeur,
        retention_jours: retention,
      });
      setMessage("Préférences enregistrées.");
    } catch (exception) {
      setErreur(
        exception instanceof ErreurApi ? exception.message : "Enregistrement impossible.",
      );
    }
  };

  return (
    <form className="carte" onSubmit={soumettre}>
      <div className="carte-titre">
        <h2>Préférences de rebond et de rétention</h2>
      </div>

      {message && <div className="message message-succes" style={{ marginBottom: 14 }}>{message}</div>}
      {erreur && <div className="message message-erreur" style={{ marginBottom: 14 }}>{erreur}</div>}

      {bride && (
        <div className="message message-alerte" style={{ marginBottom: 16 }}>
          Votre plan actuel limite ces réglages. Appliqué actuellement : mode{" "}
          <strong>
            {organisation.mode_pivot_effectif === "automatique" ? "automatique" : "supervisé"}
          </strong>
          , profondeur <strong>{organisation.profondeur_pivot_effective}</strong>. Vos
          préférences sont conservées et s'appliqueront après montée en gamme.
        </div>
      )}

      <div className="champ">
        <label htmlFor="mode">Mode de rebond</label>
        <select
          id="mode"
          value={modePivot}
          onChange={(e) => setModePivot(e.target.value as ModePivot)}
          disabled={!estAdmin}
        >
          <option value="supervise">
            Supervisé — chaque rebond attend une validation humaine
          </option>
          <option value="automatique">
            Automatique — les rebonds sont lancés directement
            {!pivotAutoDisponible ? " (plan Pro requis)" : ""}
          </option>
        </select>
        <div className="aide">
          En mode supervisé, aucune requête n'est émise vers un nouveau site tant que
          vous n'avez pas validé la piste.
        </div>
      </div>

      <div className="champ">
        <label htmlFor="profondeur">Profondeur de rebond souhaitée</label>
        <input
          id="profondeur"
          type="number"
          min={0}
          max={10}
          value={profondeur}
          onChange={(e) => setProfondeur(Number(e.target.value))}
          disabled={!estAdmin}
        />
        <div className="aide">
          Votre plan autorise {profondeurMax} niveau{profondeurMax > 1 ? "x" : ""}. Un
          plafond serveur s'applique en outre à tous les paliers, afin de maîtriser le
          volume de requêtes émises.
        </div>
      </div>

      <div className="champ">
        <label htmlFor="retention">Durée de conservation des investigations (jours)</label>
        <input
          id="retention"
          type="number"
          min={0}
          max={3650}
          value={retention}
          onChange={(e) => setRetention(Number(e.target.value))}
          disabled={!estAdmin}
        />
        <div className="aide">
          0 = valeur par défaut du serveur (90 jours). Au terme de ce délai, les
          investigations sont supprimées automatiquement — comptes, informations
          extraites et graphe compris. C'est une exigence de conformité RGPD, les
          données concernant des personnes qui n'ont pas consenti à leur collecte.
        </div>
      </div>

      {estAdmin && (
        <button type="submit" className="bouton-principal" disabled={modifier.isPending}>
          {modifier.isPending ? <span className="chargement" /> : "Enregistrer"}
        </button>
      )}
      {!estAdmin && (
        <div className="aide">Seul un administrateur peut modifier ces réglages.</div>
      )}
    </form>
  );
}

function ListeMembres({ estAdmin }: { estAdmin: boolean }) {
  const { data: membres, isLoading } = useMembres();
  const { data: abonnement } = useAbonnement();
  const inviter = useInviter();

  const [email, setEmail] = useState("");
  const [role, setRole] = useState<RoleMembre>("analyste");
  const [lienInvitation, setLienInvitation] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);
    setLienInvitation(null);
    try {
      const invitation = await inviter.mutateAsync({ email: email.trim(), role });
      // L'envoi de courriel n'est pas encore branché : on affiche le lien à
      // transmettre soi-même plutôt que de laisser croire à un envoi.
      setLienInvitation(
        `${window.location.origin}/inscription?invitation=${invitation.jeton}`,
      );
      setEmail("");
    } catch (exception) {
      setErreur(exception instanceof ErreurApi ? exception.message : "Invitation impossible.");
    }
  };

  return (
    <div className="carte">
      <div className="carte-titre">
        <h2>Membres</h2>
        {abonnement && (
          <span className="petit attenue">
            {membres?.length ?? 0} / {abonnement.plan.quota_utilisateurs} places utilisées
          </span>
        )}
      </div>

      {isLoading && <Chargement />}

      {membres && membres.length > 0 && (
        <table style={{ marginBottom: estAdmin ? 20 : 0 }}>
          <thead>
            <tr>
              <th>Adresse</th>
              <th>Nom</th>
              <th>Rôle</th>
              <th>Membre depuis</th>
            </tr>
          </thead>
          <tbody>
            {membres.map((membre) => (
              <tr key={membre.utilisateur_id}>
                <td>{membre.email}</td>
                <td className="attenue">{membre.nom_complet ?? "—"}</td>
                <td>
                  <span className="badge badge-neutre">{LIBELLES_ROLE[membre.role]}</span>
                </td>
                <td className="attenue petit">{formaterDate(membre.rejoint_le)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {estAdmin && (
        <form onSubmit={soumettre}>
          <h3 style={{ fontSize: 14, marginBottom: 10 }}>Inviter une personne</h3>

          {erreur && <div className="message message-erreur" style={{ marginBottom: 12 }}>{erreur}</div>}

          {lienInvitation && (
            <div className="message message-succes" style={{ marginBottom: 12 }}>
              Invitation créée. Transmettez ce lien à la personne concernée :
              <div className="mono petit" style={{ marginTop: 6, wordBreak: "break-all" }}>
                {lienInvitation}
              </div>
            </div>
          )}

          <div className="ligne enveloppe" style={{ gap: 10, alignItems: "flex-end" }}>
            <div className="plein champ" style={{ marginBottom: 0 }}>
              <label htmlFor="email-invite">Adresse électronique</label>
              <input
                id="email-invite"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="champ" style={{ marginBottom: 0, width: 170 }}>
              <label htmlFor="role-invite">Rôle</label>
              <select
                id="role-invite"
                value={role}
                onChange={(e) => setRole(e.target.value as RoleMembre)}
              >
                <option value="analyste">Analyste</option>
                <option value="lecteur">Lecteur</option>
                <option value="admin">Administrateur</option>
              </select>
            </div>
            <button type="submit" disabled={inviter.isPending || !email.trim()}>
              {inviter.isPending ? <span className="chargement" /> : "Inviter"}
            </button>
          </div>

          <div className="aide" style={{ marginTop: 10 }}>
            Un analyste peut lancer des recherches et valider des rebonds. Un lecteur
            consulte uniquement. L'envoi automatique de courriel n'est pas encore actif :
            transmettez le lien vous-même.
          </div>
        </form>
      )}
    </div>
  );
}

function ModulesDisponibles() {
  const { data: modules } = useModules();
  if (!modules || modules.length === 0) return null;

  return (
    <div className="carte">
      <div className="carte-titre">
        <h2>Sites couverts par un module d'enrichissement</h2>
      </div>
      <div className="ligne enveloppe" style={{ gap: 8 }}>
        {modules.map((module) => (
          <span
            key={module.nom}
            className="badge badge-neutre"
            title={module.domaines.join(", ")}
          >
            {module.libelle}
          </span>
        ))}
      </div>
      <div className="aide" style={{ marginTop: 12 }}>
        Sur ces sites, l'outil extrait biographie, avatar, localisation, liens et
        pseudonymes annexes. Les autres sites remontés par la recherche restent
        présents dans le graphe, sans enrichissement. Seuls des sites à API publique et
        documentée sont couverts, afin de ne pas exposer le service à un blocage ou à
        une violation de conditions d'utilisation.
      </div>
    </div>
  );
}
