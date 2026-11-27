"""XPLAN plan discovery as a crawler job: queue state, requester, error; geometry may come from the plan cell"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('parcel_plan_discovery') as b:
        b.add_column(sa.Column('state', sa.String(16), nullable=False, server_default='done'))
        b.add_column(sa.Column('requested_by', sa.String(40)))
        b.add_column(sa.Column('requested_at', models.UTCDateTime()))
        b.add_column(sa.Column('error', sa.Text()))
        b.alter_column('parcel_hash', existing_type=sa.String(64), nullable=True)
    op.create_index('ix_parcel_plan_discovery_state', 'parcel_plan_discovery', ['state'])


def downgrade():
    op.drop_index('ix_parcel_plan_discovery_state', 'parcel_plan_discovery')
    with op.batch_alter_table('parcel_plan_discovery') as b:
        for c in ('error', 'requested_at', 'requested_by', 'state'):
            b.drop_column(c)
