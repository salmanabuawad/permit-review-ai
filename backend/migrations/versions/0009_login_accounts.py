"""login accounts managed in the app; memberships can be revoked (user management)"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('login_accounts',
        sa.Column('username', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(40), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('must_change', sa.Boolean(), nullable=False),
        sa.Column('sessions_after', models.UTCDateTime(), nullable=True),
        sa.Column('created_by', sa.String(40), nullable=False),
        sa.Column('created_at', models.UTCDateTime(), nullable=False),
        sa.Column('password_changed_at', models.UTCDateTime(), nullable=True),
        sa.Column('last_login_at', models.UTCDateTime(), nullable=True))
    with op.batch_alter_table('authority_memberships') as b:
        b.add_column(sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('authority_memberships') as b:
        b.drop_column('active')
    op.drop_table('login_accounts')
