"""角色一致性包

从 consistency_checker.py 和 character_bible.py 整合而来。
"""
from engines.consistency.checker import ConsistencyChecker, check_consistency
from engines.consistency.bible import CharacterBible

__all__ = [
    "ConsistencyChecker", "check_consistency",
    "CharacterBible",
]
