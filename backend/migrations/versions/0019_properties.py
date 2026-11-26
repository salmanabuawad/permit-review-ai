"""Building360 property passport: properties and bitemporal property facts"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('properties',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('gush', sa.String(20), nullable=False), sa.Column('helka', sa.String(20)), sa.Column('cell', sa.String(20)),
        sa.Column('locality', sa.String(120)), sa.Column('plan', sa.String(60)), sa.Column('note_he', sa.String(300)),
        sa.Column('created_at', models.UTCDateTime(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'gush', 'helka', 'cell'))
    op.create_index('ix_properties_tenant_id', 'properties', ['tenant_id'])
    op.create_index('ix_properties_gush', 'properties', ['gush'])
    op.create_table('property_facts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('property_id', sa.Integer(), sa.ForeignKey('properties.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False), sa.Column('key', sa.String(120), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('source_type', sa.String(40), nullable=False), sa.Column('source_ref', sa.String(300)),
        sa.Column('source_url', sa.String(500)), sa.Column('valid_from', sa.Date()), sa.Column('valid_to', sa.Date()),
        sa.Column('recorded_at', models.UTCDateTime(), nullable=False), sa.Column('superseded_at', models.UTCDateTime()),
        sa.Column('recorded_by', sa.String(40), nullable=False))
    op.create_index('ix_property_facts_tenant_id', 'property_facts', ['tenant_id'])
    op.create_index('ix_property_facts_property_id', 'property_facts', ['property_id'])


def downgrade():
    op.drop_table('property_facts')
    op.drop_table('properties')
