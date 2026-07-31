"""migration Gumroad vers Stripe

Identifiant de révision : 6e6b494cb68f
Révision précédente : 1296bf46ea9e
Date de création : 2026-07-31 00:00:00.000000

Aucune vente n'a encore été faite via Gumroad (projet non lancé commercialement,
voir REPRISE.md) : les colonnes et la table liées sont remplacées directement,
sans étape de conversion des données existantes.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6e6b494cb68f'
down_revision: Union[str, None] = '1296bf46ea9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('plans', 'gumroad_product_id', new_column_name='stripe_price_id')

    op.drop_index(op.f('ix_abonnements_gumroad_license_key'), table_name='abonnements')
    op.drop_column('abonnements', 'gumroad_license_key')
    op.drop_column('abonnements', 'gumroad_product_id')
    op.drop_column('abonnements', 'gumroad_sale_id')
    op.drop_column('abonnements', 'gumroad_email_acheteur')
    op.add_column('abonnements', sa.Column('stripe_customer_id', sa.String(length=100), nullable=True))
    op.add_column('abonnements', sa.Column('stripe_subscription_id', sa.String(length=100), nullable=True))
    op.add_column('abonnements', sa.Column('stripe_price_id', sa.String(length=100), nullable=True))
    op.create_index(
        op.f('ix_abonnements_stripe_customer_id'), 'abonnements', ['stripe_customer_id'], unique=False
    )
    op.create_index(
        op.f('ix_abonnements_stripe_subscription_id'), 'abonnements', ['stripe_subscription_id'], unique=False
    )

    op.drop_index(op.f('ix_evenements_gumroad_gumroad_sale_id'), table_name='evenements_gumroad')
    op.drop_index(op.f('ix_evenements_gumroad_gumroad_license_key'), table_name='evenements_gumroad')
    op.drop_index(op.f('ix_evenements_gumroad_email'), table_name='evenements_gumroad')
    op.drop_table('evenements_gumroad')

    op.create_table(
        'evenements_stripe',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('type_evenement', sa.String(length=50), nullable=False),
        sa.Column('stripe_event_id', sa.String(length=100), nullable=True),
        sa.Column('stripe_customer_id', sa.String(length=100), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(length=100), nullable=True),
        sa.Column('charge_utile', sa.JSON(), nullable=False),
        sa.Column('traite', sa.Boolean(), nullable=False),
        sa.Column('erreur_traitement', sa.String(length=1000), nullable=True),
        sa.Column('recu_le', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_evenements_stripe')),
    )
    op.create_index(
        op.f('ix_evenements_stripe_stripe_event_id'), 'evenements_stripe', ['stripe_event_id'], unique=True
    )
    op.create_index(
        op.f('ix_evenements_stripe_stripe_customer_id'), 'evenements_stripe', ['stripe_customer_id'], unique=False
    )
    op.create_index(
        op.f('ix_evenements_stripe_stripe_subscription_id'),
        'evenements_stripe', ['stripe_subscription_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_evenements_stripe_stripe_subscription_id'), table_name='evenements_stripe')
    op.drop_index(op.f('ix_evenements_stripe_stripe_customer_id'), table_name='evenements_stripe')
    op.drop_index(op.f('ix_evenements_stripe_stripe_event_id'), table_name='evenements_stripe')
    op.drop_table('evenements_stripe')

    op.create_table(
        'evenements_gumroad',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('type_evenement', sa.String(length=50), nullable=False),
        sa.Column('gumroad_sale_id', sa.String(length=100), nullable=True),
        sa.Column('gumroad_license_key', sa.String(length=100), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('charge_utile', sa.JSON(), nullable=False),
        sa.Column('traite', sa.Boolean(), nullable=False),
        sa.Column('erreur_traitement', sa.String(length=1000), nullable=True),
        sa.Column('recu_le', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_evenements_gumroad')),
    )
    op.create_index(op.f('ix_evenements_gumroad_email'), 'evenements_gumroad', ['email'], unique=False)
    op.create_index(
        op.f('ix_evenements_gumroad_gumroad_license_key'), 'evenements_gumroad', ['gumroad_license_key'], unique=False
    )
    op.create_index(
        op.f('ix_evenements_gumroad_gumroad_sale_id'), 'evenements_gumroad', ['gumroad_sale_id'], unique=False
    )

    op.drop_index(op.f('ix_abonnements_stripe_subscription_id'), table_name='abonnements')
    op.drop_index(op.f('ix_abonnements_stripe_customer_id'), table_name='abonnements')
    op.drop_column('abonnements', 'stripe_price_id')
    op.drop_column('abonnements', 'stripe_subscription_id')
    op.drop_column('abonnements', 'stripe_customer_id')
    op.add_column('abonnements', sa.Column('gumroad_email_acheteur', sa.String(length=255), nullable=True))
    op.add_column('abonnements', sa.Column('gumroad_sale_id', sa.String(length=100), nullable=True))
    op.add_column('abonnements', sa.Column('gumroad_product_id', sa.String(length=100), nullable=True))
    op.add_column('abonnements', sa.Column('gumroad_license_key', sa.String(length=100), nullable=True))
    op.create_index(
        op.f('ix_abonnements_gumroad_license_key'), 'abonnements', ['gumroad_license_key'], unique=False
    )

    op.alter_column('plans', 'stripe_price_id', new_column_name='gumroad_product_id')
