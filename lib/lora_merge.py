"""LoRA 权重融合 (v0.5.2 功能 B)

线性插值两个(或多个) LoRA 的 safetensors 权重,产出一个新的 .safetensors。

公式: merged[key] = w_a * lora_a[key] + w_b * lora_b[key]  (key 同名时)
只融合两边都有的 key,只一边有的会**直接复制过来**(避免丢张量,
权重置 w_a 或 w_b)。

依赖: pip install safetensors  (~几 MB,纯 Python+rust 后端)
"""
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
LORAS_DIR = ROOT / "loras"


def check_safetensors() -> bool:
    try:
        import safetensors  # noqa: F401
        return True
    except ImportError:
        return False


def merge_two(
    lora_a_path: Path,
    lora_b_path: Path,
    weight_a: float = 0.5,
    weight_b: float = 0.5,
    *,
    output_path: Optional[Path] = None,
    normalize: bool = False,
    output_name: Optional[str] = None,
) -> dict:
    """融合两个 LoRA。

    weight_a / weight_b: 各自占比。如 (0.5, 0.5) 是均融, (0.7, 0.3) 偏 A。
    normalize=True 时会自动把 weight 归一到和为 1。
    output_path 默认 loras/<a-name>_x_<b-name>.safetensors
    """
    if not check_safetensors():
        return {"ok": False, "error": "未装 safetensors. pip install safetensors"}

    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    lora_a_path = Path(lora_a_path)
    lora_b_path = Path(lora_b_path)
    if not lora_a_path.exists():
        return {"ok": False, "error": f"找不到 {lora_a_path}"}
    if not lora_b_path.exists():
        return {"ok": False, "error": f"找不到 {lora_b_path}"}

    wa, wb = float(weight_a), float(weight_b)
    if normalize:
        total = wa + wb
        if total > 0:
            wa, wb = wa / total, wb / total

    if output_path is None:
        name = output_name or f"{lora_a_path.stem}_x_{lora_b_path.stem}"
        output_path = LORAS_DIR / f"{name}.safetensors"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 读两个 safetensors
    tensors_a = {}
    tensors_b = {}
    metadata = {}

    try:
        with safe_open(lora_a_path, framework="pt") as fa:
            md_a = fa.metadata() or {}
            for k in fa.keys():
                tensors_a[k] = fa.get_tensor(k)
        with safe_open(lora_b_path, framework="pt") as fb:
            md_b = fb.metadata() or {}
            for k in fb.keys():
                tensors_b[k] = fb.get_tensor(k)
    except Exception as e:
        return {"ok": False, "error": f"读取 safetensors 失败: {e}"}

    # 元数据合并
    metadata = dict(md_a)
    metadata.update(md_b)
    metadata["merged_from_a"] = lora_a_path.name
    metadata["merged_from_b"] = lora_b_path.name
    metadata["merged_weight_a"] = f"{wa:.4f}"
    metadata["merged_weight_b"] = f"{wb:.4f}"

    # 融合
    merged = {}
    keys_a = set(tensors_a.keys())
    keys_b = set(tensors_b.keys())
    common = keys_a & keys_b
    only_a = keys_a - keys_b
    only_b = keys_b - keys_a

    shape_mismatches = []
    for k in common:
        ta, tb = tensors_a[k], tensors_b[k]
        if ta.shape != tb.shape:
            shape_mismatches.append(f"{k}: {tuple(ta.shape)} vs {tuple(tb.shape)}")
            # 形状不匹配时只用 A 的(常见于 alpha 标量是 LoRA rank 标识不同)
            merged[k] = ta.clone()
            continue
        # 类型统一为 float32 做加法,然后转回原 dtype
        out_dtype = ta.dtype
        ta32 = ta.to(torch.float32)
        tb32 = tb.to(torch.float32)
        merged[k] = (wa * ta32 + wb * tb32).to(out_dtype)

    for k in only_a:
        merged[k] = tensors_a[k].clone()
    for k in only_b:
        merged[k] = tensors_b[k].clone()

    save_file(merged, str(output_path), metadata=metadata)

    return {
        "ok": True,
        "output_path": output_path,
        "size_mb": round(output_path.stat().st_size / 1024 / 1024, 1),
        "tensors": len(merged),
        "common_keys": len(common),
        "only_a_keys": len(only_a),
        "only_b_keys": len(only_b),
        "shape_mismatches": shape_mismatches,
        "weight_a": wa,
        "weight_b": wb,
    }


def auto_generate_config(
    output_lora_path: Path,
    src_a: Path,
    src_b: Path,
    wa: float, wb: float,
) -> Path:
    """给融合产物自动写一个 .json 配置(LoRA 库 Tab 可见)。"""
    import json
    from lib import lora_manager

    cfg_a = lora_manager.get_config(src_a.stem)
    cfg_b = lora_manager.get_config(src_b.stem)

    desc = (f"融合: {wa:.0%} {src_a.stem} + {wb:.0%} {src_b.stem}\n"
            f"A 描述: {cfg_a.get('description', '—')}\n"
            f"B 描述: {cfg_b.get('description', '—')}")

    tags_a = cfg_a.get("main_style_tags") or []
    tags_b = cfg_b.get("main_style_tags") or []
    merged_tags = list(dict.fromkeys(tags_a + tags_b))  # 去重保序

    rec_a = (cfg_a.get("recommended_prompt") or "").strip()
    rec_b = (cfg_b.get("recommended_prompt") or "").strip()
    if rec_a and rec_b:
        rec = f"{rec_a}, {rec_b}"
    else:
        rec = rec_a or rec_b

    config = {
        "name": output_lora_path.stem,
        "description": desc,
        "dataset_source": f"merge({src_a.name}, {src_b.name})",
        "training_steps": 0,
        "learning_rate": 0.0,
        "main_style_tags": merged_tags,
        "recommended_prompt": rec,
        "usage_notes": (f"由 lora_merge 自动融合生成。\n"
                        f"权重: A={wa:.4f}, B={wb:.4f}"),
        "merged_from_a": src_a.name,
        "merged_from_b": src_b.name,
    }
    cfg_path = output_lora_path.with_suffix(".json")
    cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return cfg_path
