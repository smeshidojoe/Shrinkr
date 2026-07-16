"""
Движок сжатия изображений. Принцип — как у Caesium (libcaesium), но на
Python-биндингах тех же инструментов:

  * JPEG — mozjpeg (mozjpeg-lossless-optimization): прогрессивный + оптимальный
    Хаффман без потерь; в режиме smart — пережатие Pillow (libjpeg-turbo) с
    заданным качеством и прогоном через mozjpeg.
  * PNG  — oxipng (pyoxipng) — безпотерьная пересборка; в режиме smart перед
    этим квантование палитры libimagequant (движок pngquant) с высоким порогом
    качества — если порог недостижим без видимых потерь, квантование
    отбрасывается автоматически.
  * WebP — libwebp (Pillow): lossless-источник пересжимается lossless method=6,
    lossy-источник в smart пережимается с заданным качеством.
  * GIF  — gifsicle -O3: lossless-пересборка; в smart дополнительно --lossy
    с малым уровнем. Фолбэк без бинарника — Pillow.
  * AVIF — libavif (pillow-avif-plugin), только как ЦЕЛЬ конвертации.

Параметры:
  mode       — "smart" (минимальные видимые потери) | "lossless"
  output     — "suffix" (name-min.ext рядом) | "overwrite"
  quality    — базовое качество smart-пережатия (60..95)
  strip      — удалять метаданные (EXIF/вспомогательные PNG-чанки)
  convert_to — "keep" | "webp" | "avif": пережать в другой формат
               (расширение результата меняется)

Правило: «минимальнейшие потери при наибольшем сжатии», разрешение не меняется.
Результат принимается только если он МЕНЬШЕ исходника; иначе файл не трогаем.
"""

import io
import os

from PIL import Image, ImageSequence

# Опциональные ускорители: без них работаем на чистом Pillow (хуже, но работает).
try:
    import mozjpeg_lossless_optimization as _mozjpeg
except ImportError:
    _mozjpeg = None

try:
    import oxipng as _oxipng
except ImportError:
    _oxipng = None

try:
    import imagequant as _imagequant
except ImportError:
    _imagequant = None

try:
    import pillow_avif  # noqa: F401 — регистрирует кодек AVIF в Pillow
    HAVE_AVIF = True
except ImportError:
    HAVE_AVIF = False

try:
    import piexif as _piexif
except ImportError:
    _piexif = None


SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# smart-режим: пережатие с потерями принимается, только если оно выигрывает у
# безпотерьного результата хотя бы на этот процент (иначе потери не оправданы).
_LOSSY_GAIN_MIN = 0.10

DEFAULT_QUALITY = 87


def is_supported(path):
    return os.path.splitext(path or "")[1].lower() in SUPPORTED_EXT


def output_path(src, mode, ext=None):
    """Путь результата. ext — новое расширение при конвертации ('.webp')."""
    base, src_ext = os.path.splitext(src)
    ext = ext or src_ext
    if mode == "overwrite" and ext.lower() == src_ext.lower():
        return src
    if mode == "overwrite":
        out = base + ext                     # конвертация: тот же basename
        if not os.path.exists(out):
            return out
    out = f"{base}-min{ext}"
    n = 2
    while os.path.exists(out):
        out = f"{base}-min ({n}){ext}"
        n += 1
    return out


def compress(src, mode="smart", output="suffix", quality=DEFAULT_QUALITY,
             strip=False, convert_to="keep"):
    """Сжимает один файл. Возвращает dict:
    {ok, out_path, orig_size, new_size, error}."""
    try:
        quality = max(40, min(100, int(quality or DEFAULT_QUALITY)))
        orig_size = os.path.getsize(src)
        with open(src, "rb") as f:
            data = f.read()

        ext = os.path.splitext(src)[1].lower()
        target = (convert_to or "keep").lower()
        if target == "avif" and not HAVE_AVIF:
            target = "keep"
        if target != "keep" and ("." + target) == (".jpeg" if ext == ".jpg" else ext):
            target = "keep"

        if target != "keep":
            best, new_ext = _convert(data, ext, target, mode, quality, strip)
        else:
            new_ext = None
            if ext in (".jpg", ".jpeg"):
                best = _compress_jpeg(data, mode, quality, strip)
            elif ext == ".png":
                best = _compress_png(data, mode, quality, strip)
            elif ext == ".webp":
                best = _compress_webp(data, mode, quality, strip)
            elif ext == ".gif":
                best = _compress_gif(data, mode)
            else:
                return {"ok": False, "error": "unsupported",
                        "orig_size": orig_size, "new_size": orig_size,
                        "out_path": src}

        if best is None or len(best) >= orig_size:
            # Пережать меньше не вышло — исходник уже оптимален.
            return {"ok": True, "out_path": src,
                    "orig_size": orig_size, "new_size": orig_size}

        out = output_path(src, output, ext=new_ext)
        _write_replace(out, best)
        # overwrite + конвертация: результат лёг рядом с новым расширением —
        # исходник убираем (замена по смыслу).
        if output == "overwrite" and os.path.abspath(out) != os.path.abspath(src):
            try:
                os.remove(src)
            except OSError:
                pass
        return {"ok": True, "out_path": out,
                "orig_size": orig_size, "new_size": len(best)}
    except Exception as e:  # noqa: BLE001 — наружу одна понятная ошибка
        return {"ok": False, "error": str(e),
                "orig_size": os.path.getsize(src) if os.path.exists(src) else 0,
                "new_size": 0, "out_path": src}


def _write_replace(path, data):
    """Атомарная запись: во временный файл рядом, затем replace."""
    tmp = path + ".shrinkr-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _pick(*candidates):
    """Наименьший из непустых кандидатов (bytes | None)."""
    best = None
    for c in candidates:
        if c and (best is None or len(c) < len(best)):
            best = c
    return best


def _meta_kwargs(img, strip):
    """ICC/EXIF для передачи в save() (пусто при strip)."""
    if strip:
        return {}
    kwargs = {}
    icc = img.info.get("icc_profile")
    exif = img.info.get("exif")
    if icc:
        kwargs["icc_profile"] = icc
    if exif:
        kwargs["exif"] = exif
    return kwargs


# ------------------------------------------------------------------ #
#  JPEG
# ------------------------------------------------------------------ #
def _strip_jpeg_exif(data):
    """Безпотерьное удаление EXIF-сегмента (piexif). Не тронет сами пиксели."""
    if _piexif is None:
        return data
    try:
        return _piexif.remove(data)
    except Exception:
        return data


def _jpeg_lossless(data, strip=False):
    """Безпотерьная оптимизация: mozjpeg (прогрессивный + оптимальный Хаффман).
    copy-параметр управляет маркерами: ALL — сохранить EXIF/ICC, NONE — убрать
    (это и есть strip для JPEG)."""
    if strip:
        data = _strip_jpeg_exif(data)     # фолбэк, если mozjpeg отсутствует
    if _mozjpeg is None:
        return None
    try:
        markers = (_mozjpeg.COPY_MARKERS.NONE if strip
                   else _mozjpeg.COPY_MARKERS.ALL)
        return _mozjpeg.optimize(data, copy=markers)
    except Exception:
        return None


def _compress_jpeg(data, mode, quality, strip):
    lossless = _jpeg_lossless(data, strip)
    if mode != "smart":
        return lossless

    # smart: пережатие с заданным качеством (субдискретизация — как в источнике).
    lossy = None
    try:
        img = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        kwargs = dict(format="JPEG", quality=quality, optimize=True,
                      progressive=True, subsampling="keep",
                      **_meta_kwargs(img, strip))
        img.save(buf, **kwargs)
        lossy = buf.getvalue()
        opt = _jpeg_lossless(lossy, strip)  # mozjpeg сверху ещё немного дожимает
        if opt and len(opt) < len(lossy):
            lossy = opt
    except Exception:
        lossy = None

    # Потери оправданы, только если дают ощутимый выигрыш против lossless.
    base = lossless if lossless else data
    if lossy and len(lossy) < len(base) * (1.0 - _LOSSY_GAIN_MIN):
        return lossy
    return lossless


# ------------------------------------------------------------------ #
#  PNG
# ------------------------------------------------------------------ #
def _png_oxipng(data, strip=False, effort=4):
    if _oxipng is None:
        return None
    try:
        kwargs = {"level": effort}
        if strip:
            kwargs["strip"] = _oxipng.StripChunks.safe()
        return _oxipng.optimize_from_memory(data, **kwargs)
    except Exception:
        return None


def _png_pillow(data):
    """Фолбэк без oxipng: пересохранение Pillow с максимальным zlib."""
    try:
        img = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True, compress_level=9)
        return buf.getvalue()
    except Exception:
        return None


def _png_quantize(data, quality):
    """Квантование палитры libimagequant с порогом качества, зависящим от
    слайдера. Если без видимых потерь не выходит — библиотека откажется."""
    if _imagequant is None:
        return None
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        min_q = max(55, quality - 12)
        q = _imagequant.quantize_pil_image(
            img, dithering_level=1.0, max_colors=256,
            min_quality=min_q, max_quality=99)
        buf = io.BytesIO()
        q.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return None       # порог качества недостижим — квантование отменяется


def _compress_png(data, mode, quality, strip):
    lossless = _pick(_png_oxipng(data, strip), _png_pillow(data))
    if mode != "smart":
        return lossless

    lossy = _png_quantize(data, quality)
    if lossy:
        lossy = _pick(_png_oxipng(lossy, strip), lossy)
    base = lossless if lossless else data
    if lossy and len(lossy) < len(base) * (1.0 - _LOSSY_GAIN_MIN):
        return lossy
    return lossless


# ------------------------------------------------------------------ #
#  WebP
# ------------------------------------------------------------------ #
def _webp_is_lossless(data):
    """RIFF-контейнер: чанк VP8L => lossless."""
    return b"VP8L" in data[:4096]


def _compress_webp(data, mode, quality, strip):
    try:
        img = Image.open(io.BytesIO(data))
        meta = _meta_kwargs(img, strip)
        src_lossless = _webp_is_lossless(data)

        if src_lossless:
            buf = io.BytesIO()
            img.save(buf, format="WEBP", lossless=True, quality=100, method=6,
                     **meta)
            lossless = buf.getvalue()
            if mode != "smart":
                return lossless
            buf2 = io.BytesIO()
            img.save(buf2, format="WEBP", quality=quality, method=6, **meta)
            lossy = buf2.getvalue()
            if lossy and len(lossy) < len(lossless) * (1.0 - _LOSSY_GAIN_MIN):
                return lossy
            return lossless

        # Источник lossy: безпотерьно улучшить нечем.
        if mode != "smart":
            return None
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality, method=6, **meta)
        lossy = buf.getvalue()
        if len(lossy) < len(data) * (1.0 - _LOSSY_GAIN_MIN):
            return lossy
        return None
    except Exception:
        return None


# ------------------------------------------------------------------ #
#  GIF
# ------------------------------------------------------------------ #
def _gif_gifsicle(data, lossy=0):
    """gifsicle -O3 через stdin/stdout."""
    from core import tools
    args = ["-O3"]
    if lossy:
        args.append(f"--lossy={int(lossy)}")
    args += ["-", "-o", "-"]
    return tools.run_gifsicle(args, input_bytes=data)


def _compress_gif(data, mode):
    lossless = _gif_gifsicle(data)
    if lossless is not None:
        if mode != "smart":
            return lossless
        lossy = _gif_gifsicle(data, lossy=30)
        if lossy and len(lossy) < len(lossless) * (1.0 - _LOSSY_GAIN_MIN):
            return lossy
        return lossless
    return _gif_pillow(data)


def _gif_pillow(data):
    """Безпотерьная пересборка (optimize=True) с сохранением анимации."""
    try:
        img = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        if getattr(img, "is_animated", False):
            frames = []
            durations = []
            for frame in ImageSequence.Iterator(img):
                frames.append(frame.copy())
                durations.append(frame.info.get("duration", 100))
            kwargs = dict(format="GIF", save_all=True, append_images=frames[1:],
                          duration=durations, optimize=True,
                          loop=img.info.get("loop", 0), disposal=2)
            if "transparency" in img.info:
                kwargs["transparency"] = img.info["transparency"]
            frames[0].save(buf, **kwargs)
        else:
            img.save(buf, format="GIF", optimize=True)
        return buf.getvalue()
    except Exception:
        return None


# ------------------------------------------------------------------ #
#  Конвертация форматов (WebP / AVIF как цель)
# ------------------------------------------------------------------ #
def _convert(data, src_ext, target, mode, quality, strip):
    """Пережатие в другой формат. Возвращает (bytes|None, '.ext')."""
    new_ext = "." + target
    try:
        img = Image.open(io.BytesIO(data))
        meta = _meta_kwargs(img, strip)
        animated = bool(getattr(img, "is_animated", False))

        if target == "webp":
            buf = io.BytesIO()
            if animated:
                frames = []
                durations = []
                for frame in ImageSequence.Iterator(img):
                    frames.append(frame.copy().convert("RGBA"))
                    durations.append(frame.info.get("duration", 100))
                frames[0].save(buf, format="WEBP", save_all=True,
                               append_images=frames[1:], duration=durations,
                               loop=img.info.get("loop", 0),
                               quality=quality, method=6, **meta)
            elif mode == "lossless" or _source_is_lossless(src_ext, data):
                # PNG/lossless-webp -> сначала пробуем lossless-webp; в smart
                # разрешаем lossy, если он ощутимо меньше.
                img.save(buf, format="WEBP", lossless=True, quality=100,
                         method=6, **meta)
                if mode == "smart":
                    buf2 = io.BytesIO()
                    img.save(buf2, format="WEBP", quality=quality, method=6, **meta)
                    if len(buf2.getvalue()) < len(buf.getvalue()) * (1.0 - _LOSSY_GAIN_MIN):
                        buf = buf2
            else:
                img.save(buf, format="WEBP", quality=quality, method=6, **meta)
            return buf.getvalue(), new_ext

        if target == "avif":
            if animated:
                return None, new_ext        # анимации в AVIF не конвертируем
            buf = io.BytesIO()
            if mode == "lossless" and _source_is_lossless(src_ext, data):
                img.save(buf, format="AVIF", quality=-1, **meta)   # -1 = lossless
            else:
                img.save(buf, format="AVIF", quality=quality, **meta)
            return buf.getvalue(), new_ext
    except Exception:
        return None, new_ext
    return None, new_ext


def _source_is_lossless(src_ext, data):
    if src_ext == ".png" or src_ext == ".gif":
        return True
    if src_ext == ".webp":
        return _webp_is_lossless(data)
    return False
