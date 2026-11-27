"""End-user self sign-up: e-mail, sign-up state and details on logins"""
from alembic import op
import sqlalchemy as sa

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('login_accounts', sa.Column('email', sa.String(254)))
    op.add_column('login_accounts', sa.Column('signup_state', sa.String(20)))
    op.add_column('login_accounts', sa.Column('signup_info', sa.JSON()))
    op.create_index('ix_login_accounts_email', 'login_accounts', ['email'])


def downgrade():
    op.drop_index('ix_login_accounts_email', 'login_accounts')
    for c in ('signup_info', 'signup_state', 'email'):
        op.drop_column('login_accounts', c)
