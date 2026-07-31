import { useState, type FormEvent } from "react";

import { ErreurApi } from "../api/client";
import {
  useActiverTotp,
  useConfirmerTotp,
  useDesactiverTotp,
  useEtatTotp,
} from "../api/hooks";
import { Chargement, MessageErreur } from "../composants/ui";
import { useAuth } from "../contexts/AuthContext";

export function PageCompte() {
  const { utilisateur } = useAuth();

  return (
    <div className="pile" style={{ gap: 24 }}>
      <div>
        <h1>Mon compte</h1>
        <p className="attenue">{utilisateur?.email}</p>
      </div>

      <SectionTotp />
    </div>
  );
}

function SectionTotp() {
  const { data: etat, isLoading, error } = useEtatTotp();
  const activer = useActiverTotp();

  // `activation` porte le secret et les codes de secours pendant la fenêtre entre
  // « activer » et « confirmer » : ils ne sont plus jamais renvoyés par le serveur
  // ensuite (le secret est chiffré en base, les codes de secours ne sont conservés
  // que sous forme d'empreinte), donc perdus si l'utilisateur quitte la page ici.
  const [activation, setActivation] = useState<{
    secret: string;
    qrCodeBase64: string;
    codesSecours: string[];
  } | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  if (isLoading) return <Chargement />;
  if (error) return <MessageErreur>Impossible de charger l'état de la double authentification.</MessageErreur>;
  if (!etat) return null;

  const demarrerActivation = async () => {
    setErreur(null);
    try {
      const reponse = await activer.mutateAsync();
      setActivation({
        secret: reponse.secret,
        qrCodeBase64: reponse.qr_code_base64,
        codesSecours: reponse.codes_secours,
      });
    } catch (exception) {
      setErreur(exception instanceof ErreurApi ? exception.message : "Activation impossible.");
    }
  };

  return (
    <div className="carte">
      <div className="carte-titre">
        <h2>Double authentification</h2>
        <span className={`badge ${etat.actif ? "badge-accent" : "badge-neutre"}`}>
          {etat.actif ? "Active" : "Inactive"}
        </span>
      </div>

      {erreur && <div className="message message-erreur" style={{ marginBottom: 14 }}>{erreur}</div>}

      <p className="attenue" style={{ marginBottom: 16 }}>
        Ajoute un code à usage unique, généré par une application d'authentification
        (Google Authenticator, Aegis, Bitwarden…), en plus du mot de passe à la
        connexion.
      </p>

      {etat.actif && !activation && <DesactivationTotp codesSecoursRestants={etat.codes_secours_restants} />}

      {!etat.actif && !activation && (
        <button type="button" className="bouton-principal" onClick={demarrerActivation} disabled={activer.isPending}>
          {activer.isPending ? <span className="chargement" /> : "Activer la double authentification"}
        </button>
      )}

      {activation && <ConfirmationTotp activation={activation} onTermine={() => setActivation(null)} />}
    </div>
  );
}

function ConfirmationTotp({
  activation,
  onTermine,
}: {
  activation: { secret: string; qrCodeBase64: string; codesSecours: string[] };
  onTermine: () => void;
}) {
  const confirmer = useConfirmerTotp();
  const [code, setCode] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [confirme, setConfirme] = useState(false);

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);
    try {
      await confirmer.mutateAsync({ code });
      setConfirme(true);
    } catch (exception) {
      setErreur(exception instanceof ErreurApi ? exception.message : "Code incorrect.");
    }
  };

  if (confirme) {
    return (
      <div className="message message-succes">
        Double authentification activée. Conservez vos codes de secours en lieu sûr :
        ils ne seront plus jamais affichés.
        <div style={{ marginTop: 10 }}>
          <button type="button" className="bouton-petit" onClick={onTermine}>
            Terminé
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="ligne" style={{ gap: 20, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div>
          <img
            src={`data:image/png;base64,${activation.qrCodeBase64}`}
            alt="QR code de configuration de la double authentification"
            width={180}
            height={180}
            style={{ border: "1px solid var(--bordure)", borderRadius: 8 }}
          />
        </div>
        <div style={{ minWidth: 240 }}>
          <p className="petit attenue">
            Scannez ce code avec votre application d'authentification, ou saisissez la
            clé manuellement :
          </p>
          <div className="mono petit" style={{ wordBreak: "break-all", marginBottom: 14 }}>
            {activation.secret}
          </div>

          <p className="petit attenue">
            <strong>Codes de secours</strong> — à conserver hors ligne. Chacun permet
            une connexion, si vous perdez l'accès à votre application :
          </p>
          <div className="mono petit" style={{ marginBottom: 14, lineHeight: 1.8 }}>
            {activation.codesSecours.join(" · ")}
          </div>
        </div>
      </div>

      <form onSubmit={soumettre} style={{ marginTop: 16 }}>
        {erreur && <div className="message message-erreur" style={{ marginBottom: 12 }}>{erreur}</div>}
        <div className="champ" style={{ maxWidth: 220 }}>
          <label htmlFor="code-confirmation">Code affiché par l'application</label>
          <input
            id="code-confirmation"
            type="text"
            inputMode="numeric"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="123456"
            autoFocus
            required
          />
        </div>
        <div className="ligne" style={{ gap: 10 }}>
          <button type="submit" className="bouton-principal" disabled={confirmer.isPending}>
            {confirmer.isPending ? <span className="chargement" /> : "Confirmer l'activation"}
          </button>
          <button type="button" className="bouton-discret" onClick={onTermine}>
            Annuler
          </button>
        </div>
      </form>
    </div>
  );
}

function DesactivationTotp({ codesSecoursRestants }: { codesSecoursRestants: number }) {
  const desactiver = useDesactiverTotp();
  const [ouvert, setOuvert] = useState(false);
  const [motDePasse, setMotDePasse] = useState("");
  const [code, setCode] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);
    try {
      await desactiver.mutateAsync({ mot_de_passe: motDePasse, code });
      setOuvert(false);
      setMotDePasse("");
      setCode("");
    } catch (exception) {
      setErreur(exception instanceof ErreurApi ? exception.message : "Désactivation impossible.");
    }
  };

  if (!ouvert) {
    return (
      <div>
        <p className="petit attenue" style={{ marginBottom: 12 }}>
          {codesSecoursRestants} code{codesSecoursRestants > 1 ? "s" : ""} de secours restant
          {codesSecoursRestants > 1 ? "s" : ""}.
        </p>
        <button type="button" className="bouton-petit bouton-danger" onClick={() => setOuvert(true)}>
          Désactiver la double authentification
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={soumettre}>
      {erreur && <div className="message message-erreur" style={{ marginBottom: 12 }}>{erreur}</div>}
      <div className="ligne enveloppe" style={{ gap: 10, alignItems: "flex-end" }}>
        <div className="champ" style={{ marginBottom: 0 }}>
          <label htmlFor="mdp-desactivation">Mot de passe</label>
          <input
            id="mdp-desactivation"
            type="password"
            value={motDePasse}
            onChange={(e) => setMotDePasse(e.target.value)}
            autoComplete="current-password"
            required
          />
        </div>
        <div className="champ" style={{ marginBottom: 0, width: 140 }}>
          <label htmlFor="code-desactivation">Code</label>
          <input
            id="code-desactivation"
            type="text"
            inputMode="numeric"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />
        </div>
        <button type="submit" className="bouton-danger" disabled={desactiver.isPending}>
          {desactiver.isPending ? <span className="chargement" /> : "Confirmer la désactivation"}
        </button>
        <button type="button" className="bouton-discret" onClick={() => setOuvert(false)}>
          Annuler
        </button>
      </div>
    </form>
  );
}
