"""LoRA 管理面板 (功能 #5)

扫描 loras/ 目录:
- 列出所有训好的 LoRA (按 .safetensors 等权重文件)
- 每个 LoRA 对应一个同名 .json 配置(描述/数据集/推荐 prompt)
- 自动生成 3 首示例曲 (用 LoRA 的推荐 prompt 套不同 seed)
- 支持多 LoRA 混合 (通过 ACE-Step lora_name_or_path,叠加权重)
"""
import json
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
LORAS_DIR = ROOT / "loras"
WEIGHT_EXTS = (".safetensors", ".bin", ".pt", ".ckpt")


# ───────────────────────────────────────────────
# 扫描
# ───────────────────────────────────────────────

def scan_loras() -> list[dict]:
    """扫描 loras/ 目录,返回每个 LoRA 的元数据。

    [{name, path, ext, size_mb, config_path, config: {...}, has_config}]
    """
    LORAS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for w in sorted(LORAS_DIR.iterdir()):
        if not w.is_file() or w.suffix.lower() not in WEIGHT_EXTS:
            continue
        cfg_path = w.with_suffix(".json")
        cfg = {}
        has_cfg = cfg_path.exists()
        if has_cfg:
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cfg = {"_error": "JSON 解析失败"}
        out.append({
            "name": w.stem,
            "path": w,
            "ext": w.suffix,
            "size_mb": round(w.stat().st_size / 1024 / 1024, 1),
            "config_path": cfg_path,
            "has_config": has_cfg,
            "config": cfg,
        })
    return out


def list_lora_names() -> list[str]:
    return [l["name"] for l in scan_loras()]


# ───────────────────────────────────────────────
# 配置读写
# ───────────────────────────────────────────────

DEFAULT_CONFIG_TEMPLATE = {
    "name": "",
    "description": "",
    "dataset_source": "",
    "training_steps": 0,
    "learning_rate": 0.0,
    "main_style_tags": [],
    "recommended_prompt": "",
    "usage_notes": "",
}


def get_config(lora_name: str) -> dict:
    cfg_path = LORAS_DIR / f"{lora_name}.json"
    if not cfg_path.exists():
        return {**DEFAULT_CONFIG_TEMPLATE, "name": lora_name}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {**DEFAULT_CONFIG_TEMPLATE, "name": lora_name, "_error": "JSON broken"}


def save_config(lora_name: str, config: dict) -> Path:
    cfg_path = LORAS_DIR / f"{lora_name}.json"
    config = dict(config)  # 拷贝防止外部 mutate
    config["name"] = lora_name  # 强制对齐
    cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return cfg_path


def delete_lora(lora_name: str, delete_weight: bool = False) -> dict:
    """删除 LoRA 配置 (默认保留权重文件,只删 .json)"""
    out = {"config_deleted": False, "weight_deleted": False}
    cfg_path = LORAS_DIR / f"{lora_name}.json"
    if cfg_path.exists():
        cfg_path.unlink()
        out["config_deleted"] = True
    if delete_weight:
        for ext in WEIGHT_EXTS:
            wp = LORAS_DIR / f"{lora_name}{ext}"
            if wp.exists():
                wp.unlink()
                out["weight_deleted"] = True
                break
    return out


# ───────────────────────────────────────────────
# 自动试听 (调 ACE-Step,#5 核心)
# ───────────────────────────────────────────────

def generate_samples(
    lora_name: str,
    *,
    prompt: Optional[str] = None,
    lyrics: str = "",
    seeds: tuple = (42, 1337, 9999),
    audio_duration: float = 30.0,
    output_dir: Optional[Path] = None,
    progress_callback=None,
) -> list[Path]:
    """对一个 LoRA 生成 N 个示例(seeds 决定数量)。

    每个 sample 用同 prompt 不同 seed,放在 outputs/lora-samples/<lora_name>/。
    如果不传 prompt, 用配置里的 recommended_prompt;再没有就报错。

    返回写入的文件路径列表。需要 ACE-Step 装好。
    """
    from lib import ace_step_api

    cfg = get_config(lora_name)
    prompt = prompt or cfg.get("recommended_prompt", "").strip()
    if not prompt:
        raise ValueError(
            f"LoRA '{lora_name}' 没有 recommended_prompt 配置,也没传 prompt 参数。"
        )

    lora_path = None
    for ext in WEIGHT_EXTS:
        candidate = LORAS_DIR / f"{lora_name}{ext}"
        if candidate.exists():
            lora_path = candidate
            break
    if lora_path is None:
        raise FileNotFoundError(f"找不到 LoRA 权重: {lora_name}")

    if output_dir is None:
        output_dir = ROOT / "outputs" / "lora-samples" / lora_name
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    paths = []
    for i, seed in enumerate(seeds, start=1):
        if progress_callback:
            progress_callback(i, len(seeds), f"seed={seed}")
        out = output_dir / f"{timestamp}_sample{i}_seed{seed}.wav"
        ace_step_api.generate(
            prompt=prompt,
            lyrics=lyrics,
            audio_duration=audio_duration,
            output_path=out,
            seed=int(seed),
            lora_name_or_path=str(lora_path),
            lora_weight=1.0,
        )
        paths.append(out)
    return paths


# ───────────────────────────────────────────────
# 多 LoRA 混合的 prompt 工具
# ───────────────────────────────────────────────

def format_mix(loras: list[tuple[str, float]]) -> str:
    """把 [(lora_name, weight), ...] 格式化成 ACE-Step 的 lora_name_or_path 字符串。

    ACE-Step 多 LoRA 语法 (基于通用 LoRA loader 推断):
    多个 LoRA 用逗号分隔,权重附在名字后,如:
        "rock-v1:1.0,female-vocal-v2:0.7"
    """
    parts = []
    for name, weight in loras:
        name = name.strip()
        if not name:
            continue
        # 确保路径
        for ext in WEIGHT_EXTS:
            p = LORAS_DIR / f"{name}{ext}"
            if p.exists():
                parts.append(f"{p}:{weight:.2f}")
                break
        else:
            parts.append(f"{name}:{weight:.2f}")
    return ",".join(parts)
