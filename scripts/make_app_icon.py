"""生成 App 图标（自适应图标 + 传统图标，全密度）。

设计：深色渐变底 + 蓝色麦克风 + 两侧声波弧线，与应用主题色一致（#6D8BFF）。
自适应图标规则：前景内容必须放在中间 72/108 的安全区内，四周会被系统裁切。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
RES = ROOT / "android/app/src/main/res"

ACCENT = (109, 139, 255)          # #6D8BFF
ACCENT_LIGHT = (150, 175, 255)
BG_TOP = (27, 36, 54)             # #1B2436
BG_BOTTOM = (15, 17, 23)          # #0F1117

# 各密度：自适应前景 108dp，传统图标 48dp
DENSITIES = {
    "mdpi": 1.0,
    "hdpi": 1.5,
    "xhdpi": 2.0,
    "xxhdpi": 3.0,
    "xxxhdpi": 4.0,
}

SS = 4          # 超采样倍数（先大后缩，边缘平滑）


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (1, size), top)
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.point((0, y), fill=c)
    return img.resize((size, size), Image.BILINEAR)


def draw_mic(size, with_bg_gradient=False):
    """画麦克风 + 声波；返回 RGBA 图。size 是最终尺寸，内部按 SS 倍超采样。

    几何参考系统 "mic" 图标：机身胶囊 → U 形支架 → 立杆 + 底座 → 两侧声波。
    自适应图标要求内容落在中间 2/3 安全区内，所以所有元素都控制在 ±42u 以内。
    """
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    if with_bg_gradient:
        # 传统图标：圆角矩形底 + 渐变
        grad = vertical_gradient(S, BG_TOP, BG_BOTTOM).convert("RGBA")
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
        img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    safe = S if with_bg_gradient else S * 2 / 3
    cx, cy = S / 2, S / 2
    u = safe / 100.0                       # 以安全区为 100 单位

    def cap_line(p1, p2, width, fill):
        """带圆头的线（PIL 没有 line cap，用两端小圆补）"""
        d.line([p1, p2], fill=fill, width=width)
        r = width / 2
        for (x, y) in (p1, p2):
            d.ellipse([x - r, y - r, x + r, y + r], fill=fill)

    # 机身胶囊（比之前小一圈，整体更接近系统图标比例）
    body_w, body_h = 19 * u, 33 * u
    body_top = cy - 27 * u
    body_left = cx - body_w / 2
    d.rounded_rectangle(
        [body_left, body_top, body_left + body_w, body_top + body_h],
        radius=body_w / 2, fill=ACCENT_LIGHT,
    )
    # 高光
    d.rounded_rectangle(
        [body_left + body_w * 0.32, body_top + body_h * 0.12,
         body_left + body_w * 0.56, body_top + body_h * 0.70],
        radius=body_w * 0.12, fill=(255, 255, 255, 95),
    )

    # U 形支架（开口朝上，把机身下半包住）
    holder_r = 15 * u
    holder_cy = cy + 6 * u
    w = max(2, int(4.5 * u))
    d.arc(
        [cx - holder_r, holder_cy - holder_r, cx + holder_r, holder_cy + holder_r],
        start=0, end=180, fill=ACCENT, width=w,
    )

    # 立杆 + 底座
    stem_top = holder_cy + holder_r
    cap_line((cx, stem_top), (cx, stem_top + 8 * u), w, ACCENT)
    base_y = stem_top + 8 * u
    cap_line((cx - 9 * u, base_y), (cx + 9 * u, base_y), w, ACCENT)

    # 两侧声波弧：只画靠内的一段，绝不越出 ±42u（否则自适应图标会被裁）
    for sign in (-1, 1):
        for rr, alpha in ((24, 200), (32, 120)):
            r = rr * u
            span = 0.62 * r
            box = [cx + sign * r - span, cy - span, cx + sign * r + span, cy + span]
            if sign > 0:
                d.arc(box, start=-52, end=52,
                      fill=(ACCENT[0], ACCENT[1], ACCENT[2], alpha), width=max(2, int(4 * u)))
            else:
                d.arc(box, start=128, end=232,
                      fill=(ACCENT[0], ACCENT[1], ACCENT[2], alpha), width=max(2, int(4 * u)))

    return img.resize((size, size), Image.LANCZOS)


def main():
    written = []

    for name, scale in DENSITIES.items():
        d = RES / f"mipmap-{name}"
        d.mkdir(parents=True, exist_ok=True)

        # 自适应图标前景：108dp，透明底，内容在安全区内
        fg_size = int(108 * scale)
        draw_mic(fg_size).save(d / "ic_launcher_foreground.png")
        written.append(d / "ic_launcher_foreground.png")

        # 传统图标：48dp 圆角方块（含渐变底），另存圆形版
        legacy = int(48 * scale)
        icon = draw_mic(legacy, with_bg_gradient=True)
        icon.save(d / "ic_launcher.png")
        written.append(d / "ic_launcher.png")

        # 圆形版：把圆角方块裁成圆
        mask = Image.new("L", (legacy * SS, legacy * SS), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, legacy * SS - 1, legacy * SS - 1], fill=255)
        mask = mask.resize((legacy, legacy), Image.LANCZOS)
        round_icon = Image.new("RGBA", (legacy, legacy), (0, 0, 0, 0))
        round_icon.paste(icon, (0, 0), mask)
        round_icon.save(d / "ic_launcher_round.png")
        written.append(d / "ic_launcher_round.png")

    # 自适应图标描述文件（API 26+）
    anydpi = RES / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    adaptive = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@drawable/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
    <monochrome android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
"""
    (anydpi / "ic_launcher.xml").write_text(adaptive, encoding="utf-8")
    (anydpi / "ic_launcher_round.xml").write_text(adaptive, encoding="utf-8")
    written += [anydpi / "ic_launcher.xml", anydpi / "ic_launcher_round.xml"]

    # 背景层：渐变
    drawable = RES / "drawable"
    drawable.mkdir(parents=True, exist_ok=True)
    bg = vertical_gradient(432, BG_TOP, BG_BOTTOM)
    bg.save(drawable / "ic_launcher_background.png")
    written.append(drawable / "ic_launcher_background.png")
    # 注意：不要再生成同名的 .xml（会和 png 冲突：Duplicate resources）

    # 预览图（放到 dist-android 便于看效果）
    preview = draw_mic(512, with_bg_gradient=True)
    out = ROOT / "dist-android/app-icon-preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    preview.save(out)

    print(f"共生成 {len(written)} 个图标文件：")
    for w in written:
        print("   ", w.relative_to(ROOT), f"{(w.stat().st_size/1024):.1f} KB")
    print("预览：", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
