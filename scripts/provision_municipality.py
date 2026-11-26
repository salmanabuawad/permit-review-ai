"""Create an isolated authority and first user. No passwords or rule approvals."""
import argparse
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.db import SessionLocal, run_migrations
from app.models import Municipality, User
from app.security import ROLES


def provision(s, tenant_id, name, uid, display_name, role='sysadmin'):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', tenant_id) or len(tenant_id) > 40 or tenant_id == 'demo':
        raise ValueError('Invalid or reserved authority ID')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', uid) or role not in ROLES or not name.strip() or not display_name.strip():
        raise ValueError('Invalid user, name or role')
    m, u = s.get(Municipality, tenant_id), s.get(User, uid)
    if m and (m.is_demo or m.name_he != name):
        raise ValueError('Authority already exists with different details')
    if u and (u.tenant_id != tenant_id or u.role != role or u.display_name != display_name):
        raise ValueError('User already exists with different details')
    if not m:
        s.add(Municipality(id=tenant_id, name_he=name, is_demo=False, settings={}))
        s.flush()
    if not u:
        s.add(User(id=uid, tenant_id=tenant_id, display_name=display_name, role=role))
    s.commit()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--id', required=True)
    p.add_argument('--name', required=True)
    p.add_argument('--user-id', required=True)
    p.add_argument('--display-name', required=True)
    p.add_argument('--role', choices=sorted(ROLES), default='sysadmin')
    a = p.parse_args()
    run_migrations()
    with SessionLocal() as s:
        provision(s, a.id, a.name, a.user_id, a.display_name, a.role)
    print('Provisioned. Configure server-side username map and htpasswd separately. No rules approved.')


if __name__ == '__main__':
    main()
