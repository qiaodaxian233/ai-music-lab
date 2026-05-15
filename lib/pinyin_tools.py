"""中文歌词 → 拼音 (v0.5.2 功能 D)

ACE-Step v1.5 训中文 LoRA 时, 用**拼音**输入比汉字识别率高很多
(模型在英文+拼音上训得多), 训中文 LoRA 必备工具。

依赖: pypinyin (~几 MB,纯 Python,装超快)
"""
import re
from typing import Optional

# 章节标签正则: [Verse 1] [Chorus] 等保留不转
SECTION_TAG_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")


def check_pypinyin() -> bool:
    try:
        import pypinyin  # noqa: F401
        return True
    except ImportError:
        return False


def to_pinyin(
    text: str,
    *,
    tone: str = "tone_marks",      # 'tone_marks' (默认带音调) / 'numbers' / 'none'
    keep_section_tags: bool = True,
    keep_punctuation: bool = True,
    word_separator: str = " ",
) -> str:
    """中文 → 拼音。

    tone:
        'tone_marks'   nǐ hǎo (默认,ACE-Step 推荐)
        'numbers'      ni3 hao3
        'none'         ni hao

    保留: 英文/数字/章节标签 [Verse]/标点(如果 keep_punctuation)
    """
    if not check_pypinyin():
        raise RuntimeError("未装 pypinyin。pip install pypinyin")

    import pypinyin
    from pypinyin import Style

    style_map = {
        "tone_marks": Style.TONE,
        "numbers": Style.TONE3,
        "none": Style.NORMAL,
    }
    style = style_map.get(tone, Style.TONE)

    out_lines = []
    for raw_line in (text or "").splitlines():
        # 保留章节标签原样
        if keep_section_tags and SECTION_TAG_RE.match(raw_line):
            out_lines.append(raw_line.strip())
            continue
        if not raw_line.strip():
            out_lines.append("")
            continue

        # 用 pinyin() 转, 保留非中文字符
        pieces = pypinyin.pinyin(
            raw_line,
            style=style,
            heteronym=False,
            errors=lambda chars: [chars] if keep_punctuation else [""],
            strict=False,
        )
        # pieces 是 [['ni3'], ['hao3'], [','], ...] 这种嵌套结构
        flat = [p[0] for p in pieces if p and p[0]]
        line = word_separator.join(flat)
        # 清理多余空格
        line = re.sub(r"\s+([,.!?;:。!?])", r"\1", line)
        line = re.sub(r"\s+", " ", line).strip()
        out_lines.append(line)

    return "\n".join(out_lines)


def to_pinyin_inline(text: str, *, tone: str = "tone_marks") -> str:
    """跟 to_pinyin 一样但去掉换行,适合塞 prompt 时用"""
    multiline = to_pinyin(text, tone=tone, keep_section_tags=False)
    return re.sub(r"\s+", " ", multiline.replace("\n", " ")).strip()


def mixed_format(text: str, *, tone: str = "tone_marks") -> str:
    """每行: 原汉字 / 拼音。debugging / lyrics editor 友好。"""
    pinyin_lines = to_pinyin(text, tone=tone).split("\n")
    orig_lines = (text or "").split("\n")
    out = []
    for orig, py in zip(orig_lines, pinyin_lines):
        if SECTION_TAG_RE.match(orig):
            out.append(orig.strip())
        elif orig.strip():
            out.append(f"{orig.strip()}\n  → {py}")
        else:
            out.append("")
    return "\n".join(out)
