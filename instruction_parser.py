import re
from typing import Tuple, Optional, Dict

def parse_companion_instruction(text: str, alias_map: Dict) -> Tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None
    raw = text.strip()
    if not raw:
        return None, None

    clean_map = alias_map or {}

    # 1. 优先整段匹配（如纯输入 "1"、"目录1"）
    if raw in clean_map:
        return clean_map[raw], None
    if raw.lower() in clean_map:
        return clean_map[raw.lower()], None

    # 2. 拆分首词与自定义标题（如 "1 架构笔记"）
    parts = re.split(r"[\s:：\-]+", raw, maxsplit=1)
    first_token = parts[0].strip()
    remaining = parts[1].strip() if len(parts) > 1 else None

    if first_token in clean_map:
        return clean_map[first_token], remaining
    if first_token.lower() in clean_map:
        return clean_map[first_token.lower()], remaining

    # 3. 未命中任何代号，整段文字作为自定义标题
    return None, raw
