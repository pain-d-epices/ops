"""secret TOTP chiffré et codes de secours

Identifiant de révision : 1296bf46ea9e
Révision précédente : c28e47b1e908
Date de création : 2026-07-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '1296bf46ea9e'
down_revision: Union[str, None] = 'c28e47b1e908'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # totp_secret contenait jusqu'ici un secret base32 en clair (jamais utilisé, la
    # 2FA n'était pas encore livrée) : élargi pour accueillir un jeton Fernet chiffré
    # (~140 caractères pour un secret de 32 caractères), qui ne tient pas dans les
    # 64 caractères d'origine.
    op.alter_column('utilisateurs', 'totp_secret', type_=sa.String(255))
    op.add_column(
        'utilisateurs',
        sa.Column(
            'totp_codes_secours',
            postgresql.JSONB().with_variant(sa.JSON(), 'sqlite'),
            nullable=False,
            server_default='[]',
        ),
    )
    op.alter_column('utilisateurs', 'totp_codes_secours', server_default=None)


def downgrade() -> None:
    op.drop_column('utilisateurs', 'totp_codes_secours')
    op.alter_column('utilisateurs', 'totp_secret', type_=sa.String(64))
