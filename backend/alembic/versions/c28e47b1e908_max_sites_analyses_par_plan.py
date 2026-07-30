"""max_sites_analyses par plan

Identifiant de révision : c28e47b1e908
Révision précédente : f222127764ac
Date de création : 2026-07-30 14:12:19.418575
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c28e47b1e908'
down_revision: Union[str, None] = 'f222127764ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `server_default` est indispensable : la table plans contient déjà des lignes, et
    # PostgreSQL refuse d'y ajouter une colonne NOT NULL sans valeur de départ. 200 est
    # la valeur du palier gratuit, donc la plus restrictive : si l'amorçage des plans
    # n'était pas rejoué, aucune organisation ne se retrouverait avec plus de droits
    # qu'avant. Le défaut est retiré ensuite, la valeur venant désormais du code
    # (`app/facturation/plans.py`, appliqué par `app.scripts.initialiser_plans`).
    op.add_column(
        'plans',
        sa.Column('max_sites_analyses', sa.Integer(), nullable=False, server_default='200'),
    )
    op.alter_column('plans', 'max_sites_analyses', server_default=None)


def downgrade() -> None:
    op.drop_column('plans', 'max_sites_analyses')
