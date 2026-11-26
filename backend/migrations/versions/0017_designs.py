"""pre-submission designs (Architect360): case kind and owner"""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('permit_cases') as b:
        b.add_column(sa.Column('kind', sa.String(20), nullable=False, server_default='application'))
        b.add_column(sa.Column('owner_id', sa.String(40), nullable=True))
    op.create_index('ix_permit_cases_kind', 'permit_cases', ['kind'])


def downgrade():
    op.drop_index('ix_permit_cases_kind', 'permit_cases')
    with op.batch_alter_table('permit_cases') as b:
        b.drop_column('owner_id')
        b.drop_column('kind')
