"""自动封面图生成 (功能 #9)

两种模式:
1. 纯本地几何模式 (默认): PIL 画渐变 + 标题文字。无需 GPU,500ms 出图。
2. SDXL 模式 (opt-in): diffusers + SDXL/SDXL-Turbo 生成。需 6-8GB VRAM。

生成的图自动:
- 写到 outputs/covers/<filename>.png
- 嵌入到对应 MP3 的 ID3 APIC (封面 tag),如果有 MP3 文件

mode='geometric' 是默认 (不依赖 SDXL),无 VRAM 占用,适合批量。
mode='sdxl' 需要 diffusers + torch + 模型权重,首次跑会下载 ~6GB。
"""
import hashlib
import io
import math
import random
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
COVERS_DIR = ROOT / "outputs" / "covers"
COVER_SIZE = 1024  # 1024x1024 (Spotify 推荐)


# ───────────────────────────────────────────────
# 几何模式 (默认 - 无 GPU)
# ───────────────────────────────────────────────

def _palette_from_seed(seed: int) -> list[tuple[int, int, int]]:
    """从 seed 派生一组协调的颜色"""
    random.seed(seed)
    # 选一个主色相,然后用相邻色相做配色
    hue = random.random()
    palette = []
    for shift in (0.0, 0.08, -0.08, 0.4, 0.5):
        h = (hue + shift) % 1.0
        s = 0.55 + random.random() * 0.3
        v = 0.6 + random.random() * 0.3
        palette.append(_hsv_to_rgb(h, s, v))
    return palette


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    i = int(h * 6)
    f = h * 6 - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    i = i % 6
    r, g, b = [
        (v, t, p), (q, v, p), (p, v, t),
        (p, q, v), (t, p, v), (v, p, q),
    ][i]
    return int(r * 255), int(g * 255), int(b * 255)


def make_cover_geometric(
    title: str,
    *,
    subtitle: str = "",
    seed: Optional[int] = None,
    output_path: Optional[Path] = None,
    size: int = COVER_SIZE,
) -> Path:
    """画一张几何风格的封面 (无 GPU 依赖,~500ms)。

    每首歌的 seed 决定配色 + 几何形状,所以同 prompt 出同图。
    没传 seed 则从 title hash 算一个稳定 seed。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except ImportError:
        raise RuntimeError("Pillow 未安装。pip install pillow")

    if seed is None:
        seed = int(hashlib.md5(title.encode("utf-8")).hexdigest()[:8], 16)

    palette = _palette_from_seed(seed)
    bg, accent1, accent2, hl1, hl2 = palette

    img = Image.new("RGB", (size, size), bg)

    # 1) 径向渐变背景 (从中心淡入主色)
    grad = Image.new("RGB", (size, size), bg)
    gd = ImageDraw.Draw(grad)
    cx, cy = size // 2, size // 2
    max_r = int(size * 0.9)
    for r in range(max_r, 0, -10):
        t = r / max_r
        c = (
            int(bg[0] * t + accent1[0] * (1 - t)),
            int(bg[1] * t + accent1[1] * (1 - t)),
            int(bg[2] * t + accent1[2] * (1 - t)),
        )
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    grad = grad.filter(ImageFilter.GaussianBlur(40))
    img.paste(grad)

    # 2) 几何块
    random.seed(seed + 1)
    draw = ImageDraw.Draw(img, "RGBA")
    n_shapes = random.randint(3, 6)
    for _ in range(n_shapes):
        kind = random.choice(["circle", "circle", "stripe", "arc"])
        color = random.choice([accent2, hl1, hl2])
        alpha = random.randint(80, 180)
        rgba = (*color, alpha)
        if kind == "circle":
            r = random.randint(size // 8, size // 3)
            x = random.randint(0, size)
            y = random.randint(0, size)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=rgba)
        elif kind == "stripe":
            y = random.randint(0, size)
            h = random.randint(20, 80)
            draw.rectangle([0, y, size, y + h], fill=rgba)
        elif kind == "arc":
            r = random.randint(size // 4, size // 2)
            x = random.randint(0, size)
            y = random.randint(0, size)
            width = random.randint(10, 40)
            draw.arc([x - r, y - r, x + r, y + r],
                     start=random.randint(0, 360),
                     end=random.randint(0, 360),
                     fill=rgba, width=width)

    # 模糊一下让形状柔和
    img = img.filter(ImageFilter.GaussianBlur(3))

    # 3) 标题文字
    draw = ImageDraw.Draw(img)
    title_short = title[:40] + ("…" if len(title) > 40 else "")
    font_title = _try_load_font(int(size * 0.07))
    font_sub = _try_load_font(int(size * 0.035))

    # 测量文字
    try:
        bbox = draw.textbbox((0, 0), title_short, font=font_title)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = font_title.getsize(title_short)

    x = (size - tw) // 2
    y = int(size * 0.65)

    # 黑色阴影 + 白色文字, 增强可读性
    for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
        draw.text((x + dx, y + dy), title_short, fill=(0, 0, 0, 200), font=font_title)
    draw.text((x, y), title_short, fill=(255, 255, 255), font=font_title)

    if subtitle:
        try:
            bbox = draw.textbbox((0, 0), subtitle, font=font_sub)
            sw = bbox[2] - bbox[0]
        except Exception:
            sw = font_sub.getsize(subtitle)[0]
        x = (size - sw) // 2
        y_sub = y + th + 20
        draw.text((x, y_sub), subtitle, fill=(255, 255, 255, 220), font=font_sub)

    # 写盘
    if output_path is None:
        safe_stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in title)[:50]
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = COVERS_DIR / f"{safe_stem}_{seed:x}.png"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG", optimize=True)
    return output_path


def _try_load_font(size: int):
    """尝试加载系统字体,失败回退到 PIL 默认。"""
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/PingFang.ttc",  # mac
        "C:/Windows/Fonts/msyhbd.ttc",  # win 微软雅黑
        "C:/Windows/Fonts/arialbd.ttf",  # win
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ───────────────────────────────────────────────
# SDXL 模式 (opt-in)
# ───────────────────────────────────────────────

def make_cover_sdxl(
    prompt: str,
    *,
    title_overlay: str = "",
    output_path: Optional[Path] = None,
    model_id: str = "stabilityai/sdxl-turbo",
    num_inference_steps: int = 4,
    seed: Optional[int] = None,
) -> Path:
    """用 SDXL 生成图,然后(可选)在底部叠 title 文字。

    默认用 sdxl-turbo (4 步出图,~5 秒),也可以传 stabilityai/stable-diffusion-xl-base-1.0。
    首次跑会下载 ~6GB 模型。
    """
    try:
        import torch
        from diffusers import AutoPipelineForText2Image
    except ImportError:
        raise RuntimeError(
            "需要 diffusers + torch。\n"
            "  pip install diffusers transformers accelerate\n"
            "或者用 mode='geometric' (不需 GPU)。"
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    pipe = AutoPipelineForText2Image.from_pretrained(
        model_id, torch_dtype=dtype, variant="fp16" if dtype == torch.float16 else None,
    )
    pipe = pipe.to(device)
    # 显存优化
    if device == "cuda":
        pipe.enable_attention_slicing()
        try:
            pipe.enable_model_cpu_offload()
        except Exception:
            pass

    generator = None
    if seed is not None:
        generator = torch.Generator(device=device).manual_seed(int(seed))

    image = pipe(
        prompt=prompt,
        num_inference_steps=num_inference_steps,
        guidance_scale=0.0 if "turbo" in model_id.lower() else 7.0,
        generator=generator,
        height=COVER_SIZE,
        width=COVER_SIZE,
    ).images[0]

    if title_overlay:
        try:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
            font = _try_load_font(int(COVER_SIZE * 0.07))
            # 简单底部黑色横条 + 白字
            bar_h = int(COVER_SIZE * 0.15)
            from PIL import Image as _Im
            overlay = _Im.new("RGBA", image.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.rectangle([0, image.height - bar_h, image.width, image.height],
                         fill=(0, 0, 0, 180))
            image = _Im.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(image)
            draw.text((40, image.height - bar_h + 20), title_overlay[:40],
                      fill=(255, 255, 255), font=font)
        except Exception:
            pass

    if output_path is None:
        safe_stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in prompt)[:50]
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = COVERS_DIR / f"{safe_stem}_sdxl.png"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return output_path


# ───────────────────────────────────────────────
# 嵌入到 MP3 的 ID3
# ───────────────────────────────────────────────

def embed_into_mp3(mp3_path: Path, image_path: Path) -> bool:
    """把封面图嵌入到 MP3 的 ID3 APIC tag。成功返 True。"""
    try:
        from mutagen.id3 import ID3, APIC, ID3NoHeaderError
    except ImportError:
        raise RuntimeError("需要 mutagen。pip install mutagen")

    mp3_path = Path(mp3_path)
    if mp3_path.suffix.lower() != ".mp3":
        return False  # ID3 APIC 只搞 MP3

    img_bytes = Path(image_path).read_bytes()
    mime = "image/png" if str(image_path).lower().endswith(".png") else "image/jpeg"

    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    # 去掉旧封面
    tags.delall("APIC")
    tags.add(APIC(
        encoding=3,   # utf-8
        mime=mime,
        type=3,       # 3 = 封面 (front cover)
        desc="Cover",
        data=img_bytes,
    ))
    tags.save(mp3_path)
    return True
