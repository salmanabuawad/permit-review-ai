"""national register of local planning committees"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('planning_committees',
        sa.Column('id', sa.String(40), primary_key=True),
        sa.Column('committee_code', sa.String(40), nullable=True),
        sa.Column('name_he', sa.String(200), nullable=False, unique=True),
        sa.Column('district', sa.String(40), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('website_url', sa.String(500), nullable=True),
        sa.Column('engineering_url', sa.String(500), nullable=True),
        sa.Column('request_search_url', sa.String(500), nullable=True),
        sa.Column('vendor', sa.String(40), nullable=False),
        sa.Column('vendor_evidence', sa.String(300), nullable=True),
        sa.Column('sources', sa.JSON(), nullable=False),
        sa.Column('kb_status', sa.String(30), nullable=False),
        sa.Column('kb_detail', sa.JSON(), nullable=False),
        sa.Column('registry_source', sa.JSON(), nullable=False),
        sa.Column('last_probed_at', models.UTCDateTime(), nullable=True),
        sa.Column('updated_at', models.UTCDateTime(), nullable=False))
    op.create_index('ix_planning_committees_district', 'planning_committees', ['district'])
    op.create_table('committee_settlements',
        sa.Column('committee_id', sa.String(40), sa.ForeignKey('planning_committees.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('name_he', sa.String(200), primary_key=True))
    with op.batch_alter_table('municipalities') as b:
        b.add_column(sa.Column('committee_id', sa.String(40), nullable=True))
        b.create_foreign_key('fk_municipalities_committee', 'planning_committees', ['committee_id'], ['id'])


def downgrade():
    with op.batch_alter_table('municipalities') as b:
        b.drop_constraint('fk_municipalities_committee', type_='foreignkey')
        b.drop_column('committee_id')
    op.drop_table('committee_settlements')
    op.drop_table('planning_committees')
