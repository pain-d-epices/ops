"""Données extraites sans profil porteur

Une information issue d'un point de départ (le nom derrière une adresse Gravatar,
l'opérateur d'un numéro) ne se rattache à aucun compte : elle décrit la personne
recherchée, pas un profil trouvé sur un site.

`donnees_extraites.profil_id` étant jusqu'ici obligatoire, ces informations étaient
**purement et simplement perdues** quand la recherche ne trouvait aucun compte —
c'est-à-dire précisément dans le cas où elles avaient le plus de valeur. Mesuré en
conditions réelles le 01/08/2026 : une recherche par adresse électronique remontait
un profil Gravatar (nom affiché, localisation, avatar) dont rien n'était conservé en
base, et qui ne pouvait donc ni être affiché, ni servir de rebond.

Revision ID: b7d41e05c3a2
Revises: 6e6b494cb68f
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7d41e05c3a2"
down_revision = "6e6b494cb68f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "donnees_extraites",
        "profil_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )


def downgrade() -> None:
    # Les données sans profil porteur ne peuvent pas être conservées par une colonne
    # non nulle : elles sont supprimées avant de rétablir la contrainte.
    op.execute("DELETE FROM donnees_extraites WHERE profil_id IS NULL")
    op.alter_column(
        "donnees_extraites",
        "profil_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
