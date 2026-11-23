#!/usr/bin/env python3
"""Осьминог-аватар Git Hunter для вертикальных видео.

Маленький оранжевый осьминог в стиле логотипа сидит в самом низу кадра,
покачивается, открывает рот в такт голосу и иногда указывает щупальцем
на слайды. Субтитры поднимаются, чтобы он их не загораживал.

Синхронизация губ: амплитуда RMS аудио по кадрам (основной сигнал),
плюс интервалы слов edge-tts, если они есть (в паузах рот закрывается).
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ORANGE = (246, 90, 5, 255)
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
MOUTH_IN = (90, 18, 8, 255)
TONGUE = (190, 45, 32, 255)

# Холст наложения в кадре 1080×1920: осьминог маленький, у самого низа.
OW, OH = 460, 430
MARGIN_BOTTOM = 10
# Верх наложения ≈ 1480; субтитры должны заканчиваться выше этого.
OCTOPUS_TOP_Y = 1920 - OH - MARGIN_BOTTOM  # 1480
SUB_Y_WITH_AVATAR = 1280

SPRITE_SIZE = 512
FPS_DEFAULT = 30

# Порядок рисования щупалец: сначала дальние, потом передние.
TENTACLE_ORDER = [2, 5, 1, 6, 0, 7, 3, 4]

# Предпочтительный мужской голос и запасные темпы (Dmitry часто сбоит на +5%).
MALE_VOICE = "ru-RU-DmitryNeural"
DMITRY_RATES = ("-5%", "-8%", "+0%", "-3%", "+3%")
def _piper_male_models():
    """Мужские модели Piper: переменные окружения, кэш Actions, локальный ящик."""
    names = (
        "ru_RU-dmitri-medium.onnx",
        "ru_RU-ruslan-medium.onnx",
        "ru_RU-denis-medium.onnx",
    )
    out = []
    env = os.environ.get("PIPER_MODEL")
    if env:
        out.append(Path(env))
    roots = [
        Path(os.environ["PIPER_DIR"]) if os.environ.get("PIPER_DIR") else None,
        Path.home() / ".local/share/piper",
        Path("/home/box/.zavod_tts"),
        Path("/opt/piper"),
    ]
    for root in roots:
        if not root:
            continue
        for name in names:
            cand = root / name
            if cand not in out:
                out.append(cand)
    return tuple(out)


PIPER_DMITRI = Path.home() / ".local/share/piper" / "ru_RU-dmitri-medium.onnx"
PIPER_MALE_MODELS = _piper_male_models()  # пересчитываем при импорте; tts_piper смотрит exists()


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def bezier(p0, p1, p2, p3, n=60):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append((
            u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
        ))
    return pts


def _stroke(draw, pts, width, fill):
    r = width / 2.0
    ip = [(int(round(x)), int(round(y))) for x, y in pts]
    draw.line(ip, fill=fill, width=max(1, int(round(width))), joint="curve")
    for p in (ip[0], ip[-1]):
        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=fill)


def _tentacle_specs(phase=0.0, point=0.0, point_side=1):
    # Координаты в единицах rx широкой круглой головы (как купол на логотипе).
    specs = [
        ((-0.92, 0.12), (-1.50, -0.22), (-2.20, 0.10), (-1.68, 0.58)),
        ((-0.96, 0.48), (-1.58, 0.40), (-2.10, 0.95), (-1.58, 1.28)),
        ((-0.78, 0.82), (-1.35, 1.20), (-2.00, 2.05), (-2.05, 2.48)),
        ((-0.35, 1.02), (-0.45, 1.65), (-0.32, 2.35), (-0.92, 2.70)),
        ((0.35, 1.02), (0.45, 1.65), (0.32, 2.35), (0.92, 2.70)),
        ((0.78, 0.82), (1.35, 1.20), (2.00, 2.05), (2.05, 2.48)),
        ((0.96, 0.48), (1.58, 0.40), (2.10, 0.95), (1.58, 1.28)),
        ((0.92, 0.12), (1.50, -0.22), (2.20, 0.10), (1.68, 0.58)),
    ]
    # Поза «указывает вверх на слайды» для правого (или левого) mid-hook.
    point_idx = 6 if point_side >= 0 else 1
    if point_side >= 0:
        point_pose = ((0.92, 0.35), (1.10, -0.15), (1.00, -0.95), (0.78, -1.55))
    else:
        point_pose = ((-0.92, 0.35), (-1.10, -0.15), (-1.00, -0.95), (-0.78, -1.55))

    out = []
    for i, (a, b, c, e) in enumerate(specs):
        ph = phase + i * 0.73
        sx = 0.07 * math.sin(ph)
        sy = 0.05 * math.sin(ph * 0.85 + 1.1)
        b = (b[0] + sx * 0.35, b[1] + sy * 0.25)
        c = (c[0] + sx * 0.80, c[1] + sy * 0.65)
        e = (e[0] + sx, e[1] + sy)
        if point > 0 and i == point_idx:
            pa, pb, pc, pe = point_pose
            k = point
            a = (a[0] + (pa[0] - a[0]) * k, a[1] + (pa[1] - a[1]) * k)
            b = (b[0] + (pb[0] - b[0]) * k, b[1] + (pb[1] - b[1]) * k)
            c = (c[0] + (pc[0] - c[0]) * k, c[1] + (pc[1] - c[1]) * k)
            e = (e[0] + (pe[0] - e[0]) * k, e[1] + (pe[1] - e[1]) * k)
        elif point > 0 and i == (7 if point_side >= 0 else 0):
            # соседнее верхнее щупальце чуть поднимается вместе с жестом
            e = (e[0] * (1 - 0.12 * point), e[1] - 0.45 * point)
            c = (c[0], c[1] - 0.25 * point)
        out.append((a, b, c, e))
    return out


def draw_octopus(size=SPRITE_SIZE, mouth=0.0, blink=0.0, phase=0.0, point=0.0, point_side=1):
    """Спрайт осьминога. mouth, blink, point — от 0 до 1."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Широкая круглая голова-купол, как на логотипе (не вытянутое яйцо).
    cx, cy = size * 0.50, size * 0.36
    rx = size * 0.225
    ry = rx * 1.12
    outline = max(6, int(rx * 0.22))
    tent_outer = max(10, int(rx * 0.62))
    tent_inner = max(6, tent_outer - outline)

    specs = _tentacle_specs(phase, point, point_side)

    def P(p):
        return (cx + p[0] * rx, cy + p[1] * rx)

    for i in TENTACLE_ORDER:
        a, b, c, e = specs[i]
        pts = bezier(P(a), P(b), P(c), P(e))
        _stroke(draw, pts, tent_outer, BLACK)
        _stroke(draw, pts, tent_inner, ORANGE)

    draw.ellipse(
        [cx - rx - outline / 2, cy - ry - outline / 2, cx + rx + outline / 2, cy + ry + outline / 2],
        fill=BLACK,
    )
    draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=ORANGE)

    # Глаза в нижней части широкой головы, как на логотипе.
    eye_rx, eye_ry = rx * 0.195, rx * 0.215
    eye_y = cy + ry * 0.36
    gap = rx * 0.40
    pupil_r = rx * 0.09
    for sign in (-1, 1):
        ex, ey = cx + sign * gap, eye_y
        if blink >= 0.85:
            w = eye_rx * 1.05
            draw.line([(ex - w, ey), (ex + w, ey)], fill=BLACK, width=max(4, int(rx * 0.08)))
        else:
            ryy = eye_ry * (1.0 - 0.88 * blink)
            draw.ellipse([ex - eye_rx, ey - ryy, ex + eye_rx, ey + ryy], fill=WHITE)
            if blink < 0.55:
                pr = pupil_r * (1.0 - 0.25 * blink)
                px = ex - sign * rx * 0.025
                py = ey - rx * 0.04  # смотрит немного вверх, на слайды
                draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=BLACK)

    mx, my = cx, cy + ry * 0.72
    if mouth < 0.10:
        w = rx * 0.22
        pts = []
        for i in range(15):
            t = i / 14
            pts.append((
                int(round(mx - w + 2 * w * t)),
                int(round(my + rx * 0.055 * math.sin(math.pi * t))),
            ))
        draw.line(pts, fill=BLACK, width=max(5, int(rx * 0.09)), joint="curve")
        r = max(2, int(rx * 0.045))
        for p in (pts[0], pts[-1]):
            draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=BLACK)
    else:
        mw = rx * (0.16 + 0.24 * mouth)
        mh = rx * (0.07 + 0.26 * mouth)
        draw.ellipse([mx - mw, my - mh, mx + mw, my + mh], fill=BLACK)
        if mouth > 0.22:
            inset = max(3, rx * 0.045)
            draw.ellipse(
                [mx - mw + inset, my - mh + inset, mx + mw - inset, my + mh - inset],
                fill=MOUTH_IN,
            )
            if mouth > 0.65:
                tw = mw * 0.48
                draw.ellipse(
                    [mx - tw, my + mh * 0.10, mx + tw, my + mh - inset * 0.6],
                    fill=TONGUE,
                )
    return img


def save_reference_sprites(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for name, kw in (
        ("closed", dict(mouth=0)),
        ("half", dict(mouth=0.45)),
        ("open", dict(mouth=1)),
        ("blink", dict(mouth=0, blink=1)),
        ("point", dict(mouth=0.55, point=1)),
    ):
        draw_octopus(768, **kw).save(folder / f"{name}.png")


# ------------------------------------------------------------------ голос
def split_sentences(text: str):
    import re
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    out = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) > 220:
            chunks = re.split(r"(?<=[,;:—–-])\s+", part)
            buf = ""
            for c in chunks:
                if buf and len(buf) + len(c) > 180:
                    out.append(buf.strip())
                    buf = c
                else:
                    buf = (buf + " " + c).strip()
            if buf:
                out.append(buf)
        else:
            out.append(part)
    return out or [text.strip()]


async def _edge_tts(text, voice, rate):
    import edge_tts
    words, buf = [], bytearray()
    kwargs = {"boundary": "WordBoundary"}
    if rate:
        kwargs["rate"] = rate
    comm = edge_tts.Communicate(text, voice, **kwargs)
    async for ch in comm.stream():
        if ch["type"] == "audio":
            buf.extend(ch["data"])
        elif ch["type"] == "WordBoundary":
            words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
    if len(buf) < 4000:
        raise RuntimeError("пустой ответ edge-tts")
    return bytes(buf), words


def _try_dmitry(text, rate):
    import asyncio
    return asyncio.run(_edge_tts(text, MALE_VOICE, rate))


def _write_mp3(data: bytes, path: Path):
    path.write_bytes(data)
    return path


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out or 0)


def _concat_audio(parts: list[Path], dest: Path, pause=0.12):
    """Склеить mp3/wav куски в один mp3, с короткой паузой между фразами."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        wavs = []
        for i, p in enumerate(parts):
            w = td / f"p{i}.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(p), str(w)],
                check=True,
            )
            wavs.append(w)
            if i < len(parts) - 1 and pause > 0:
                sil = td / f"s{i}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
                     "-t", f"{pause}", str(sil)],
                    check=True,
                )
                wavs.append(sil)
        lst = td / "list.txt"
        lst.write_text("".join(f"file '{w}'\n" for w in wavs), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c:a", "libmp3lame", "-q:a", "4", str(dest)],
            check=True,
        )


def tts_dmitry(text: str, mp3: Path, attempts_per_rate: int = 1):
    """Синтез ru-RU-DmitryNeural. Сначала весь текст (пара попыток), при неудаче — по предложениям.
    Возвращает (words, 'ru-RU-DmitryNeural') или бросает исключение."""
    import time

    rates = list(DMITRY_RATES)
    # полная фраза: две ставки, по одной попытке — дальше надёжнее колоть на предложения
    for rate in rates[:2]:
        for n in range(attempts_per_rate):
            try:
                data, words = _try_dmitry(text, rate)
                if words:
                    _write_mp3(data, mp3)
                    log(f"  голос: {MALE_VOICE} rate={rate} (целиком, слов={len(words)})")
                    return words, MALE_VOICE
            except Exception as e:
                log(f"  Dmitry {rate} попытка {n+1}: {type(e).__name__}: {e}")
                time.sleep(2 * (n + 1))

    # по предложениям
    sentences = split_sentences(text)
    log(f"  Dmitry: пробую по предложениям ({len(sentences)})")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        all_words = []
        parts = []
        t_off = 0.0
        for i, sent in enumerate(sentences):
            got = None
            for rate in rates:
                try:
                    data, words = _try_dmitry(sent, rate)
                    if data:
                        part = td / f"s{i}.mp3"
                        _write_mp3(data, part)
                        for a, b, w in words:
                            all_words.append((a + t_off, b + t_off, w))
                        t_off += _duration(part) + 0.12
                        parts.append(part)
                        got = rate
                        break
                except Exception as e:
                    log(f"  Dmitry предл.{i+1} {rate}: {type(e).__name__}")
                    time.sleep(2)
            if got is None:
                raise RuntimeError(f"Dmitry не озвучил предложение {i+1}: {sent[:80]}")
        _concat_audio(parts, mp3)
        log(f"  голос: {MALE_VOICE} (по предложениям, слов={len(all_words)})")
        return all_words, MALE_VOICE


def tts_piper_male(text: str, mp3: Path):
    """Запасной мужской русский голос (Piper dmitri / ruslan / denis). Без женских."""
    model = next((p for p in _piper_male_models() if p.exists()), None)
    if model is None:
        raise RuntimeError(
            "Нет мужского голоса: edge-tts Dmitry не ответил и модели Piper не найдены. "
            "Ожидается мужская ru_RU-dmitri-medium в $PIPER_MODEL / $PIPER_DIR "
            "или ~/.local/share/piper/"
        )
    wav = mp3.with_suffix(".wav")
    proc = subprocess.run(
        ["piper", "-m", str(model), "-f", str(wav)],
        input=text, text=True, capture_output=True,
    )
    if proc.returncode != 0 or not wav.exists() or wav.stat().st_size < 1000:
        raise RuntimeError("piper: " + (proc.stderr or proc.stdout or "нет аудио")[-800:])
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav),
         "-c:a", "libmp3lame", "-q:a", "4", str(mp3)],
        check=True,
    )
    wav.unlink(missing_ok=True)
    name = f"piper:{model.stem}"
    log(f"  голос: {name} (запасной мужской, без таймингов слов)")
    return None, name


def tts_male(text: str, mp3: Path):
    """Только мужской голос. Никогда не падает на женский."""
    mp3 = Path(mp3)
    mp3.parent.mkdir(parents=True, exist_ok=True)
    try:
        return tts_dmitry(text, mp3)
    except Exception as e:
        log(f"  Dmitry не удался ({e}); запасной мужской Piper")
        return tts_piper_male(text, mp3)


# ------------------------------------------------------------------ губы и жесты
def audio_rms_series(path: Path, fps: int, nframes: int, lead: float = 0.0, sr: int = 22050):
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
    )
    samples = np.frombuffer(raw, dtype=np.float32)
    # лид — тишина в начале ролика, до старта голоса
    pad = np.zeros(int(round(lead * sr)), dtype=np.float32)
    samples = np.concatenate([pad, samples])
    hop = sr / fps
    win = max(2, int(sr * 0.028))  # окно ~28 мс, рот реагирует быстро
    rms = np.zeros(nframes, dtype=np.float32)
    for i in range(nframes):
        c = int(i * hop)
        a = max(0, c - win // 2)
        b = min(len(samples), a + win)
        if b > a:
            chunk = samples[a:b]
            rms[i] = float(np.sqrt(np.mean(chunk * chunk)))
    # нормализация по 92-му процентилю звучащих кадров
    voice = rms[rms > 1e-4]
    peak = (np.percentile(voice, 92) if len(voice) > 10 else rms.max()) or 1e-3
    env = np.clip(rms / peak, 0, 1.2)
    # небольшое сглаживание, чтобы рот не «трещал», но оставался живым
    smooth = np.zeros_like(env)
    acc = 0.0
    for i, v in enumerate(env):
        acc = acc * 0.42 + v * 0.58
        smooth[i] = acc
    return smooth


def apply_word_gating(mouth: np.ndarray, words, lead: float, fps: int):
    """В паузах между словами прижимаем рот к закрытому."""
    if not words:
        return mouth
    n = len(mouth)
    open_mask = np.zeros(n, dtype=np.float32)
    for a, b, _ in words:
        i0 = max(0, int(round((lead + a - 0.03) * fps)))
        i1 = min(n, int(round((lead + b + 0.04) * fps)))
        open_mask[i0:i1] = 1.0
    # чуть расширить маску, чтобы согласные не хлопали
    ker = 2
    dil = open_mask.copy()
    for i in range(n):
        dil[i] = open_mask[max(0, i - ker): min(n, i + ker + 1)].max()
    # в тишине — не выше 0.12, в речи оставляем RMS
    return np.where(dil > 0.5, mouth, np.minimum(mouth, 0.12) * 0.4)


def blink_series(nframes: int, fps: int, seed: int = 7):
    rng = np.random.default_rng(seed)
    blink = np.zeros(nframes, dtype=np.float32)
    t = 1.6 + rng.random() * 0.8
    while t < (nframes / fps) - 0.3:
        i0 = int(t * fps)
        # 3–4 кадра закрытия
        dur = 3 if rng.random() > 0.25 else 4
        for k in range(dur):
            if i0 + k < nframes:
                # 0, 1, 1, 0
                blink[i0 + k] = 1.0 if k in (1, 2) or dur == 3 and k == 1 else (0.6 if k in (0, dur - 1) else 1.0)
        if rng.random() < 0.18:  # редкое двойное моргание
            t += 0.18
        else:
            t += 2.6 + rng.random() * 1.6
    return blink


def point_series(nframes: int, fps: int, first=4.6, every=7.4, hold=1.25):
    """Плавный жест «показывает на слайды» каждые several секунд."""
    point = np.zeros(nframes, dtype=np.float32)
    t = first
    total = nframes / fps
    side = []
    s = 1
    while t + hold < total - 2.2:  # не на финальной карточке
        s = -s
        for i in range(nframes):
            ti = i / fps
            if t <= ti <= t + hold:
                u = (ti - t) / hold
                # ease in-out: 0→1→0
                if u < 0.22:
                    p = 0.5 - 0.5 * math.cos(math.pi * u / 0.22)
                elif u > 0.75:
                    p = 0.5 + 0.5 * math.cos(math.pi * (u - 0.75) / 0.25)
                else:
                    p = 1.0
                point[i] = max(point[i], p)
                if len(side) <= i:
                    side.extend([s] * (i + 1 - len(side)))
        t += every + (0.4 if s > 0 else 0.0)
    if len(side) < nframes:
        side.extend([1] * (nframes - len(side)))
    return point, np.array(side[:nframes], dtype=np.int8)


# ------------------------------------------------------------------ наложение
def _compose_frame(mouth, blink, phase, point, point_side, bob_x, bob_y, angle, cache):
    key = (int(round(mouth * 8)), 1 if blink >= 0.7 else 0, int(round(point * 5)), int(round(phase * 6)) % 6, int(point_side))
    if key not in cache:
        cache[key] = draw_octopus(
            SPRITE_SIZE,
            mouth=key[0] / 8,
            blink=1.0 if key[1] else 0.0,
            phase=key[3] * (math.pi * 2 / 6),
            point=key[2] / 5,
            point_side=point_side,
        ).resize((OW - 40, OW - 40), Image.LANCZOS)
    spr = cache[key]
    if abs(angle) > 0.15:
        spr = spr.rotate(angle, resample=Image.BICUBIC, expand=False)
    canvas = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    # мягкая тень «плавает»
    shadow = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sx = OW // 2 + int(bob_x)
    sy = OH - 28 + int(bob_y * 0.4)
    sd.ellipse([sx - 110, sy - 16, sx + 110, sy + 16], fill=(0, 0, 0, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    canvas.alpha_composite(shadow)
    px = (OW - spr.width) // 2 + int(bob_x)
    py = OH - spr.height - 2 + int(bob_y)
    canvas.alpha_composite(spr, (px, py))
    return canvas


def render_overlay(audio_path: Path, duration: float, out_mov: Path, lead: float = 0.3,
                   fps: int = FPS_DEFAULT, words=None) -> dict:
    """Пишет прозрачный ролик осьминога (qtrle/argb) длительностью duration."""
    n = int(round(duration * fps))
    mouth = audio_rms_series(audio_path, fps, n, lead=lead)
    mouth = apply_word_gating(mouth, words, lead, fps)
    blinks = blink_series(n, fps)
    points, sides = point_series(n, fps)
    cache = {}

    proc = subprocess.Popen(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{OW}x{OH}", "-r", str(fps),
            "-i", "-",
            "-c:v", "qtrle", "-pix_fmt", "argb",
            str(out_mov),
        ],
        stdin=subprocess.PIPE,
    )
    mid = {"t": 0.0, "mouth": -1.0}
    for i in range(n):
        t = i / fps
        phase = t * 2.2
        bob_y = 9 * math.sin(2 * math.pi * t / 1.75)
        bob_x = 6 * math.sin(2 * math.pi * t / 2.65)
        angle = 3.2 * math.sin(2 * math.pi * t / 3.15)
        frame = _compose_frame(
            float(mouth[i]), float(blinks[i]), phase,
            float(points[i]), int(sides[i]),
            bob_x, bob_y, angle, cache,
        )
        proc.stdin.write(frame.tobytes())
        # кадр «середина речи» — максимальный рот в средней трети
        if duration * 0.28 <= t <= duration * 0.72 and float(mouth[i]) > mid["mouth"]:
            mid = {"t": t, "mouth": float(mouth[i])}
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError("ffmpeg overlay encode failed")
    return mid


def overlay_on_video(src_mp4: Path, overlay_mov: Path, dest_mp4: Path):
    x = (1080 - OW) // 2
    y = OCTOPUS_TOP_Y
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src_mp4), "-i", str(overlay_mov),
        "-filter_complex", f"[0:v][1:v]overlay={x}:{y}:format=auto[v]",
        "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "27",
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(dest_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg overlay: " + r.stderr[-1500:])


def add_octopus(src_mp4: Path, audio_path: Path, dest_mp4: Path, lead: float = 0.3,
                words=None, work: Path | None = None) -> dict:
    own = work is None
    if own:
        td = tempfile.TemporaryDirectory()
        work = Path(td.name)
    try:
        dur = _duration(src_mp4)
        ov = work / "octopus.mov"
        mid = render_overlay(audio_path, dur, ov, lead=lead, words=words)
        overlay_on_video(src_mp4, ov, dest_mp4)
        return mid
    finally:
        if own:
            td.cleanup()


def extract_frame(video: Path, t: float, dest: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(dest)],
        check=True,
    )


def build_sample():
    """Один пробный ролик из подборки за 2026-11-23, без записи в data/ и без публикации."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import json
    import make_videos as mv

    root = Path(__file__).resolve().parent.parent
    date = os.environ.get("VIDEO_DATE", "2026-11-23")
    day = json.loads((root / f"data/{date}.json").read_text(encoding="utf-8"))
    idx = int(os.environ.get("VIDEO_INDEX") or 0)
    p = day["projects"][idx]
    out_mp4 = Path(os.environ.get("SAMPLE_OUT") or "/workspace/octopus-sample.mp4")
    out_png = Path(os.environ.get("SAMPLE_FRAME") or "/workspace/octopus-frame.png")
    log('образец:', p['full_name'], '→', out_mp4)

    save_reference_sprites(root / "assets" / "octopus")
    mv.SUB_Y = SUB_Y_WITH_AVATAR

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        audio = td / "narration.mp3"
        # build_video сам наложит осьминога и озвучит мужским голосом
        total, synced = mv.build_video(p, td, out_mp4, audio)
        voice = mv.tts_with_words.last_voice
        log(f"  ролик: {total:.1f}s, субтитры синхронны: {synced}, голос: {voice}")
        # кадр в середине речи — пик рта по RMS
        n = int(round(total * FPS_DEFAULT))
        mouth = audio_rms_series(audio, FPS_DEFAULT, n, lead=mv.LEAD)
        mid_i = None
        mid_v = -1
        for i, v in enumerate(mouth):
            t = i / FPS_DEFAULT
            if total * 0.28 <= t <= total * 0.68 and float(v) > mid_v:
                mid_v, mid_i = float(v), i
        t = (mid_i / FPS_DEFAULT) if mid_i is not None else total * 0.45
        extract_frame(out_mp4, t, out_png)
        mb = out_mp4.stat().st_size / 1e6
        log(f"  кадр речи t={t:.2f}s mouth={mid_v:.2f} → {out_png}")
        log(f"  готово: {out_mp4} ({mb:.1f} MB), голос={voice}")
        return {"voice": voice, "total": total, "frame_t": t, "project": p["full_name"]}


if __name__ == "__main__":
    if "--sprites" in sys.argv:
        dest = Path(sys.argv[sys.argv.index("--sprites") + 1]) if len(sys.argv) > sys.argv.index("--sprites") + 1 and not sys.argv[sys.argv.index("--sprites") + 1].startswith("-") else Path("/tmp/octopus-sprites")
        save_reference_sprites(dest)
        log("sprites →", dest)
    else:
        build_sample()
