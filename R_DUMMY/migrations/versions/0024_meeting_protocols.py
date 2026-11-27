"""Meeting protocols (decision files): per-meeting state, per-item protocol sections and the decision's source"""
from alembic import op
import sqlalchemy as sa

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('committee_meetings') as b:
        b.add_column(sa.Column('protocol_state', sa.String(16)))
    with op.batch_alter_table('committee_meeting_items') as b:
        b.add_column(sa.Column('protocol', sa.JSON()))
        b.add_column(sa.Column('decision_source', sa.String(16)))


def downgrade():
    with op.batch_alter_table('committee_meeting_items') as b:
        b.drop_column('decision_source')
        b.drop_column('protocol')
    with op.batch_alter_table('committee_meetings') as b:
        b.drop_column('protocol_state')
