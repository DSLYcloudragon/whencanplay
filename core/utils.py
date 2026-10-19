"""项目里到处要用的小工具。"""

import secrets
import string

# 去掉容易看错的 0/o、1/l，邀请码要让人能手抄
ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'


def random_code(length=8):
    """生成一串随机的短标识，用于群链接和邀请码。"""
    return ''.join(secrets.choice(ALPHABET) for _ in range(length))
