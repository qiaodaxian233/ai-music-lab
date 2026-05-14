"""Prompt 预设库 (功能 #4)

读写 prompts/styles.json,支持:
- 列出所有 preset (名称 → prompt 字符串)
- 按分类列出 tag 积木块
- 组合 tags 成 prompt
- 新增 / 删除 / 重命名 preset (写回 JSON,保留 _comment / _writing_tips 等)

整个项目只读写一个文件: prompts/styles.json
"""
import json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
STYLES_JSON = ROOT / "prompts" / "styles.json"


# ───────────────────────────────────────────────
# IO
# ───────────────────────────────────────────────

def _default_db() -> dict:
    return {
        "_comment": "风格 tag 预设库",
        "presets": {},
        "tags-by-category": {},
        "_writing_tips": [],
    }


def load_db() -> dict:
    if not STYLES_JSON.exists():
        return _default_db()
    try:
        return json.loads(STYLES_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _default_db()


def save_db(db: dict) -> None:
    STYLES_JSON.parent.mkdir(parents=True, exist_ok=True)
    STYLES_JSON.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ───────────────────────────────────────────────
# 读 API
# ───────────────────────────────────────────────

def list_presets() -> list[tuple[str, str]]:
    """[(preset_name, prompt_string), ...] 按字母排序"""
    db = load_db()
    return sorted(db.get("presets", {}).items())


def get_preset(name: str) -> Optional[str]:
    return load_db().get("presets", {}).get(name)


def list_categories() -> list[str]:
    return list(load_db().get("tags-by-category", {}).keys())


def list_tags(category: str) -> list[str]:
    return load_db().get("tags-by-category", {}).get(category, [])


def get_writing_tips() -> list[str]:
    return load_db().get("_writing_tips", [])


# ───────────────────────────────────────────────
# 写 API
# ───────────────────────────────────────────────

def save_preset(name: str, prompt: str) -> bool:
    """新建或覆盖一个 preset。返回是否新建 (True=新建, False=覆盖)"""
    name = name.strip()
    prompt = prompt.strip()
    if not name or not prompt:
        raise ValueError("名称和 prompt 都不能为空")
    db = load_db()
    db.setdefault("presets", {})
    is_new = name not in db["presets"]
    db["presets"][name] = prompt
    save_db(db)
    return is_new


def delete_preset(name: str) -> bool:
    db = load_db()
    if name not in db.get("presets", {}):
        return False
    del db["presets"][name]
    save_db(db)
    return True


def rename_preset(old: str, new: str) -> bool:
    new = new.strip()
    if not new:
        raise ValueError("新名称不能为空")
    db = load_db()
    presets = db.get("presets", {})
    if old not in presets:
        return False
    if new in presets and new != old:
        raise ValueError(f"名称已存在: {new}")
    presets[new] = presets.pop(old)
    db["presets"] = presets
    save_db(db)
    return True


# ───────────────────────────────────────────────
# 工具
# ───────────────────────────────────────────────

def compose_prompt(*parts: str) -> str:
    """把多段 tag/词组拼成 prompt,去掉空段,逗号分隔。"""
    chunks = []
    for p in parts:
        if not p:
            continue
        # 允许传入逗号分隔的字符串或单 tag
        for piece in p.split(","):
            piece = piece.strip()
            if piece and piece not in chunks:
                chunks.append(piece)
    return ", ".join(chunks)
