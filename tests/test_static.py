from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

for path in ROOT.rglob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'))

membership = (ROOT / 'handlers' / 'membership.py').read_text(encoding='utf-8')
assert 'ban_chat_member' in (ROOT / 'services' / 'ban_service.py').read_text(encoding='utf-8')
assert '@router.chat_member()' in membership
assert 'ChatMemberStatus.LEFT' in membership
assert 'get_chat_member' in membership
print('STATIC TESTS PASSED')
