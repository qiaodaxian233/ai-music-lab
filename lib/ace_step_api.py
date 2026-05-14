"""ACE-Step pipeline 调用封装 (功能 #6 #11 #12 共用)

封装对 ACE-Step-1.5 Python pipeline 的调用,提供:
- text-to-music (普通生成,#6 批量用)
- audio-extend (续写,#11 用)
- audio-to-audio (翻唱,#12 用)

设计原则:
- 懒加载: ACE-Step 占显存大,只在第一次调用时 import
- 单例: 整个进程只加载一次模型,后续调用复用
- 容错: 如果 ACE-Step 未安装/路径不对,raise 清晰的中文错误
- ACE-Step 的 Pipeline API 在不同 commit 上参数名可能微调,如果调用失败,
  报错信息里会指明哪个参数不对,用户去 ACE-Step-1.5/acestep/pipeline_ace_step.py
  查实际签名再调整本文件

⚠ 重要: 本文件基于 ACE-Step v1.5 主线 (2025-04 ~ 2026-05) 的 pipeline.__call__ 签名
推断。如果跑批量生成报"unexpected keyword argument",去查 ACE-Step 实际 API。
"""
import sys
import threading
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
ACE_STEP_DIR = ROOT / "ACE-Step-1.5"

_pipeline = None
_pipeline_lock = threading.Lock()


# ───────────────────────────────────────────────
# 加载
# ───────────────────────────────────────────────

def ace_step_available() -> bool:
    """ACE-Step 是否已 clone 到本地"""
    return ACE_STEP_DIR.exists() and (ACE_STEP_DIR / "acestep").exists()


def get_pipeline(checkpoint_dir: Optional[Path] = None,
                 dtype: str = "bfloat16",
                 torch_compile: bool = False,
                 cpu_offload: bool = True,
                 overlapped_decode: bool = True):
    """获取(或惰性加载)ACE-Step pipeline 单例。

    参数都是 ACE-Step 官方推荐的 12GB VRAM 友好配置。
    cpu_offload + overlapped_decode 让显存压力大幅降低。
    torch_compile=True 首次会编译几分钟,但后续推理更快;
    批量场景建议开,单次 / 调试时关。
    """
    global _pipeline
    with _pipeline_lock:
        if _pipeline is not None:
            return _pipeline

        if not ace_step_available():
            raise RuntimeError(
                f"ACE-Step 未安装到 {ACE_STEP_DIR}。\n"
                f"先跑 bash setup.sh 安装。"
            )

        # 把 ACE-Step 目录加进 sys.path
        if str(ACE_STEP_DIR) not in sys.path:
            sys.path.insert(0, str(ACE_STEP_DIR))

        try:
            from acestep.pipeline_ace_step import ACEStepPipeline  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                f"无法 import acestep.pipeline_ace_step: {e}\n"
                f"确认 ACE-Step-1.5/acestep/ 存在且依赖装好。"
            ) from e

        kwargs = dict(
            dtype=dtype,
            torch_compile=torch_compile,
            cpu_offload=cpu_offload,
            overlapped_decode=overlapped_decode,
        )
        if checkpoint_dir is not None:
            kwargs["checkpoint_dir"] = str(checkpoint_dir)

        _pipeline = ACEStepPipeline(**kwargs)
        return _pipeline


def unload_pipeline():
    """卸载 pipeline 释放显存(批量任务做完调用)。"""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            return
        try:
            import gc
            import torch
            del _pipeline
            _pipeline = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            _pipeline = None


# ───────────────────────────────────────────────
# 生成 API
# ───────────────────────────────────────────────

def generate(
    prompt: str,
    lyrics: str = "",
    *,
    audio_duration: float = 60.0,
    output_path: Path,
    seed: Optional[int] = None,
    infer_step: int = 60,
    guidance_scale: float = 15.0,
    scheduler_type: str = "euler",
    cfg_type: str = "apg",
    omega_scale: float = 10.0,
    lora_name_or_path: Optional[str] = None,
    lora_weight: float = 1.0,
    **extra,
) -> Path:
    """普通 text-to-music 生成,把结果写入 output_path。

    output_path 父目录会自动建。返回 output_path。
    """
    pipeline = get_pipeline()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    call_kwargs = dict(
        prompt=prompt,
        lyrics=lyrics,
        audio_duration=float(audio_duration),
        infer_step=int(infer_step),
        guidance_scale=float(guidance_scale),
        scheduler_type=scheduler_type,
        cfg_type=cfg_type,
        omega_scale=float(omega_scale),
        save_path=str(output_path),
    )
    if seed is not None:
        call_kwargs["manual_seeds"] = str(seed)
    if lora_name_or_path:
        call_kwargs["lora_name_or_path"] = lora_name_or_path
        call_kwargs["lora_weight"] = float(lora_weight)
    call_kwargs.update(extra)

    pipeline(**call_kwargs)
    return output_path


def extend(
    source_audio: Path,
    extend_seconds: float,
    *,
    output_path: Path,
    prompt: str = "",
    lyrics: str = "",
    seed: Optional[int] = None,
    direction: str = "tail",  # "head" 头部续写, "tail" 尾部续写(默认)
    **extra,
) -> Path:
    """对已有歌续写 N 秒 (功能 #11)。

    direction='tail' 在末尾续 N 秒, 'head' 在开头加 N 秒。
    ACE-Step audio2audio 模式,task='extend',通过 src_audio_path + ref_audio_strength
    控制连贯性。
    """
    pipeline = get_pipeline()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    call_kwargs = dict(
        task="extend",
        prompt=prompt,
        lyrics=lyrics,
        src_audio_path=str(source_audio),
        repaint_start=-1 if direction == "head" else 0,  # head=负数代表向前续
        repaint_end=float(extend_seconds),
        save_path=str(output_path),
    )
    if seed is not None:
        call_kwargs["manual_seeds"] = str(seed)
    call_kwargs.update(extra)

    pipeline(**call_kwargs)
    return output_path


def cover(
    source_audio: Path,
    *,
    new_prompt: str,
    new_lyrics: str = "",
    output_path: Path,
    ref_audio_strength: float = 0.5,
    seed: Optional[int] = None,
    **extra,
) -> Path:
    """翻唱 (功能 #12): 保留 source 的旋律/结构,换新风格新词。

    ref_audio_strength: 0=完全新生成, 1=完全照搬, 0.4~0.6 是甜区。
    ACE-Step audio2audio task='audio2audio'。
    """
    pipeline = get_pipeline()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    call_kwargs = dict(
        task="audio2audio",
        prompt=new_prompt,
        lyrics=new_lyrics,
        src_audio_path=str(source_audio),
        ref_audio_strength=float(ref_audio_strength),
        save_path=str(output_path),
    )
    if seed is not None:
        call_kwargs["manual_seeds"] = str(seed)
    call_kwargs.update(extra)

    pipeline(**call_kwargs)
    return output_path
