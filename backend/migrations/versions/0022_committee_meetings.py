"""Committee meetings and their items (public decisions) — for study and validation only, never an engine input"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('committee_meetings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('committee_id', sa.String(32), sa.ForeignKey('planning_committees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type_code', sa.String(8), nullable=False), sa.Column('type_he', sa.String(60)),
        sa.Column('meeting_number', sa.String(20), nullable=False), sa.Column('real_number', sa.String(20)),
        sa.Column('meeting_date', sa.Date()), sa.Column('protocol_ref', sa.String(40)),
        sa.Column('state', sa.String(16), nullable=False), sa.Column('items', sa.Integer()), sa.Column('error', sa.Text()),
        sa.Column('fetched_at', models.UTCDateTime()),
        sa.UniqueConstraint('committee_id', 'type_code', 'meeting_number', name='uq_committee_meeting'))
    op.create_index('ix_committee_meetings_state', 'committee_meetings', ['state'])
    op.create_table('committee_meeting_items',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('meeting_id', sa.Integer(), sa.ForeignKey('committee_meetings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item_number', sa.String(10), nullable=False), sa.Column('item_type', sa.String(80)),
        sa.Column('subject', sa.String(300)), sa.Column('request_ref', sa.String(60)), sa.Column('plan', sa.String(60)),
        sa.Column('locality', sa.String(120)), sa.Column('gush', sa.String(20)), sa.Column('helka', sa.String(20)),
        sa.Column('migrash', sa.String(20)), sa.Column('parcels', sa.Text()),
        sa.Column('essence', sa.Text()), sa.Column('reliefs', sa.Text()), sa.Column('decision', sa.Text()),
        sa.Column('outcome', sa.String(30)), sa.Column('state', sa.String(16), nullable=False),
        sa.Column('fetched_at', models.UTCDateTime()),
        sa.UniqueConstraint('meeting_id', 'item_number', name='uq_meeting_item'))
    op.create_index('ix_committee_meeting_items_state', 'committee_meeting_items', ['state'])
    op.create_index('ix_committee_meeting_items_outcome', 'committee_meeting_items', ['outcome'])


def downgrade():
    op.drop_table('committee_meeting_items')
    op.drop_table('committee_meetings')
