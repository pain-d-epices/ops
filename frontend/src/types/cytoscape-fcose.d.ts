/**
 * Déclaration de type pour cytoscape-fcose, qui n'en fournit pas.
 * L'extension s'enregistre auprès de Cytoscape et n'expose pas d'API propre.
 */
declare module "cytoscape-fcose" {
  import type cytoscape from "cytoscape";
  const extension: cytoscape.Ext;
  export default extension;
}
