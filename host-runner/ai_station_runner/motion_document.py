"""Trusted, seekable Hyperframes document compiler for typed editorial scenes.

Text stays escaped HTML text. All asset names are assigned by the owned launch,
not provided by a model. Executable animation code and CSS are fixed here.
"""

import html
import json

from ai_station_runner.motion_contract import Composition


def luminance(color):
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(first, second):
    a, b = sorted((luminance(first), luminance(second)))
    return (b + 0.05) / (a + 0.05)


def colors(style):
    accent = style.palette[0]
    background = style.palette[1] if len(style.palette) > 1 else "#101311"
    requested = style.palette[2] if len(style.palette) > 2 else "#F7F8F4"
    foreground = (
        requested
        if contrast(requested, background) >= 4.5
        else max(("#FFFFFF", "#111111"), key=lambda color: contrast(color, background))
    )
    accent_ink = accent if contrast(accent, background) >= 3 else foreground
    return dict(accent=accent, background=background, foreground=foreground, accent_ink=accent_ink)


def text(value):
    return html.escape(value, quote=True)


def element(tag, value, cls):
    return f'<{tag} class="{cls}">{text(value)}</{tag}>' if value else ""


def document(composition: Composition, assets=None, *, audio=False):
    assets = assets or {}
    portrait = composition.height > composition.width
    palette = colors(composition.style)
    family = {
        "sans": "Inter Variable",
        "humanist": "Manrope Variable",
        "editorial": "EB Garamond Variable",
        "mono": "JetBrains Mono Variable",
    }[composition.style.typography]
    scenes, animation = [], []
    start = 0
    for index, scene in enumerate(composition.scenes):
        sid = f"scene-{index}"
        points = "".join(
            f'<li class="reveal"><span class="point-number">{n + 1:02}</span><span>{text(point)}</span></li>'
            for n, point in enumerate(scene.points)
        )
        metrics = "".join(
            f'<div class="metric reveal"><strong>{text(metric.value)}</strong><span>{text(metric.label)}</span></div>'
            for metric in scene.metrics
        )
        media = ""
        if scene.media:
            key = str(scene.media)
            if key not in assets or assets[key] not in {
                f"assets/media-{n}{suffix}" for n in range(60) for suffix in (".png", ".jpg", ".webp", ".mp4")
            }:
                raise ValueError("Scene media is not a frozen owned asset")
            path = assets[key]
            if path.endswith(".mp4"):
                media = f'<video id="media-{index}" class="clip scene-media" src="{path}" data-start="{start / 30}" data-duration="{scene.duration_frames / 30}" data-media-start="{scene.media_start_seconds}" muted playsinline style="object-fit:{scene.media_fit}"></video>'
            else:
                media = f'<img class="scene-media" src="{path}" alt="" style="object-fit:{scene.media_fit}">'
            media = f'<div class="media-frame reveal">{media}</div>'
        content = (
            element("div", scene.eyebrow, "eyebrow reveal")
            + element("h1", scene.title, "title reveal")
            + element("p", scene.body, "body reveal")
            + (f'<ol class="points">{points}</ol>' if points else "")
            + (f'<div class="metrics">{metrics}</div>' if metrics else "")
        )
        scenes.append(
            f'<section id="{sid}" class="scene layout-{scene.layout}{" has-media" if media else ""}" data-scene-start="{start / 30}" data-scene-duration="{scene.duration_frames / 30}" style="z-index:{index}">'
            + '<div class="scene-inner"><span class="accent-rule"></span><div class="scene-copy">'
            + content
            + "</div>"
            + media
            + "</div>"
            + f"<footer><span>{text(composition.style.brand)}</span><span>{index + 1:02} / {len(composition.scenes):02}</span></footer>"
            + "</section>"
        )
        time = start / 30
        end = (start + scene.duration_frames) / 30
        # Scene wrappers are untimed: nested video owns absolute timing itself.
        # Trusted GSAP controls scene visibility; never nest timed clips.
        # Avoid unseeded effects,
        # infinite repeats, wall-clock time or text interpolated into JavaScript.
        animation.append(f'tl.set("#{sid}",{{visibility:"visible"}},{time});')
        if index < len(composition.scenes) - 1:
            animation.append(f'tl.set("#{sid}",{{visibility:"hidden"}},{end});')
        strength = {"gentle": 32, "dynamic": 72, "minimal": 0}[composition.style.motion]
        stagger = min(0.065, scene.duration_frames / 30 / 40)
        animation.append(
            f'tl.fromTo("#{sid} .reveal",{{opacity:0,y:{strength}}},{{opacity:1,y:0,duration:0.38,stagger:{stagger},ease:"power3.out",immediateRender:false}},{time});'
        )
        if scene.media:
            kind = scene.media_motion
            if kind == "auto":
                kind = "hold" if assets[str(scene.media)].endswith(".mp4") else "push_in"
            movements = {
                "push_in": ({"scale": 1}, {"scale": 1.1}),
                "pull_out": ({"scale": 1.1}, {"scale": 1}),
                "pan_left": ({"scale": 1.14, "xPercent": 5}, {"scale": 1.14, "xPercent": -5}),
                "pan_right": ({"scale": 1.14, "xPercent": -5}, {"scale": 1.14, "xPercent": 5}),
                "rise": ({"scale": 1.14, "yPercent": 5}, {"scale": 1.14, "yPercent": -5}),
            }
            if kind in movements:
                first, last = movements[kind]
                last = {
                    **last,
                    "duration": scene.duration_frames / 30,
                    "ease": "none",
                    "immediateRender": False,
                }
                animation.append(
                    f'tl.fromTo("#{sid} .scene-media",{json.dumps(first)},{json.dumps(last)},{time});'
                )
        if index < len(composition.scenes) - 1:
            animation.append(
                f'tl.to("#{sid} .scene-inner",{{opacity:0,y:-8,duration:0.18,ease:"power2.in"}},{max(time + 0.6, end - 0.18)});'
            )
        start += scene.duration_frames
    css = f"""
:root{{--accent:{palette["accent"]};--bg:{palette["background"]};--ink:{palette["foreground"]};--accent-ink:{palette["accent_ink"]}}}
*{{box-sizing:border-box}}html,body{{margin:0;width:{composition.width}px;height:{composition.height}px;overflow:hidden;background:var(--bg)}}
body{{font-family:'{family}','Inter Variable',sans-serif;color:var(--ink);-webkit-font-smoothing:antialiased}}
#main{{position:relative;width:100%;height:100%;overflow:hidden;background:var(--bg)}}
.scene{{position:absolute;inset:0;background:var(--bg);overflow:hidden;visibility:hidden}}
.scene-inner{{position:absolute;inset:{"170px 110px 300px 88px" if portrait else "105px 128px 150px"};display:flex;flex-direction:column;justify-content:center;gap:34px}}
.accent-rule{{display:block;width:76px;height:6px;background:var(--accent);flex-shrink:0}}
.scene-copy{{min-width:0;max-width:100%}}
.eyebrow{{font-family:'Inter Variable',sans-serif;color:var(--accent-ink);font-size:{24 if portrait else 22}px;letter-spacing:.14em;text-transform:uppercase;line-height:1.5;margin-bottom:30px;overflow-wrap:anywhere}}
.title{{font-size:{92 if portrait else 102}px;line-height:1.08;letter-spacing:-.045em;margin:0 0 34px;font-weight:700;overflow-wrap:anywhere;text-wrap:balance}}
.body{{font-size:{36 if portrait else 38}px;line-height:1.5;margin:0;overflow-wrap:anywhere;text-wrap:pretty;white-space:pre-line}}
.points{{list-style:none;display:grid;gap:24px;padding:0;margin:34px 0 0}}
.points li{{display:flex;gap:24px;align-items:baseline;font-size:{32 if portrait else 34}px;line-height:1.45;overflow-wrap:anywhere}}
.point-number{{font:20px 'Inter Variable',sans-serif;color:var(--accent-ink);flex-shrink:0}}
.metrics{{display:grid;grid-template-columns:repeat({1 if portrait else 3},minmax(0,1fr));gap:32px;margin-top:40px}}
.metric{{display:flex;flex-direction:column;gap:12px;padding:26px 0;border-top:2px solid var(--accent)}}
.metric strong{{font-size:{94 if portrait else 100}px;line-height:1.1;letter-spacing:-.05em;overflow-wrap:anywhere}}
.metric span{{font-size:{28 if portrait else 26}px;line-height:1.4;overflow-wrap:anywhere}}
.layout-quote .title{{font-weight:400;font-style:italic;line-height:1.22}}
.layout-closing .title{{font-size:{100 if portrait else 116}px}}
.has-media .scene-inner{{display:grid;grid-template-columns:{"1fr" if portrait else "1fr 1fr"};grid-template-rows:{"auto 1fr" if portrait else "1fr"};align-items:center;gap:48px}}
.has-media .accent-rule{{display:none}}
.has-media .title{{font-size:{72 if portrait else 76}px}}
.has-media .body{{font-size:30px}}
.media-frame{{min-width:0;min-height:0;width:100%;height:100%;max-height:{600 if portrait else 760}px;border-radius:24px;overflow:hidden}}
.scene-media{{width:100%;height:100%;display:block}}
.layout-full_bleed .scene-inner{{display:block;inset:0}}
.layout-full_bleed .media-frame{{position:absolute;inset:0;max-height:none;border-radius:0;z-index:0}}
.layout-full_bleed .media-frame::after{{content:'';position:absolute;inset:0;background:linear-gradient(to top,var(--bg) 0%,{palette["background"]}EF 24%,{palette["background"]}A0 52%,transparent 82%)}}
.layout-full_bleed .scene-copy{{position:absolute;z-index:2;left:{88 if portrait else 128}px;right:{110 if portrait else 128}px;bottom:{340 if portrait else 180}px;max-height:65%}}
.layout-full_bleed footer{{z-index:3}}
footer{{position:absolute;left:{88 if portrait else 128}px;right:{110 if portrait else 128}px;bottom:{215 if portrait else 70}px;display:flex;justify-content:space-between;gap:40px;font:20px 'Inter Variable',sans-serif;color:var(--ink);opacity:.65}}
footer span:first-child{{max-width:75%;overflow-wrap:anywhere}}
"""
    # Fit copy before render; fail a QC check rather than crop unreadable text.
    # The final smallest allowed typography is still legible at full HD.
    fit = """
window.__stationLayout = [];
for (const node of document.querySelectorAll('.scene')) {
  const inner = node.querySelector('.scene-inner');
  const copy = node.querySelector('.scene-copy');
  let scale = 1;
  const measured = [...copy.querySelectorAll('.title,.body,.eyebrow,.points li,.metric strong,.metric span')].map(el=>[el,parseFloat(getComputedStyle(el).fontSize)]);
  while ((inner.scrollHeight > inner.clientHeight + 2 || copy.scrollHeight > copy.clientHeight + 2 || copy.scrollWidth > copy.clientWidth + 2) && scale > 0.64) {
    scale -= 0.02;
    for (const [el,size] of measured) el.style.fontSize = (size * scale) + 'px';
  }
  window.__stationLayout.push({scene:node.id,scale,overflow:inner.scrollHeight > inner.clientHeight + 2 || copy.scrollHeight > copy.clientHeight + 2 || copy.scrollWidth > copy.clientWidth + 2});
}
"""
    sound = (
        '<audio id="soundtrack" class="clip" src="assets/mix.wav" data-start="0" data-duration="'
        + str(composition.frames / 30)
        + '" data-track-index="99" data-volume="1"></audio>'
        if audio
        else ""
    )
    js = (
        "const tl=gsap.timeline({paused:true});"
        + "".join(animation)
        + 'window.__timelines["main"]=tl;tl.seek(0);'
    )
    # Metadata excludes user content from executable JS and records contrast
    # corrections separately from the user's original identity.
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:\">"
        + "".join(
            f'<link rel="stylesheet" href="assets/fonts/{name}/index.css">'
            for name in ("inter", "manrope", "eb-garamond", "jetbrains-mono")
        )
        + f'<style>{css}</style><script src="assets/gsap.min.js"></script></head><body>'
        f'<div id="main" data-composition-id="main" data-start="0" data-duration="{composition.frames / 30}" data-width="{composition.width}" data-height="{composition.height}">'
        + "".join(scenes)
        + sound
        + "</div>"
        + f"<script>window.__timelines=window.__timelines||{{}};window.__stationReady=(async()=>{{const sample=[...document.querySelectorAll('.scene')].map(n=>n.textContent).join(' ');await Promise.all(['{family}','Inter Variable'].flatMap(f=>[400,700].map(w=>document.fonts.load(w+' 36px \\\"'+f+'\\\"',sample))));await document.fonts.ready;{fit}{js}}})();</script></body></html>"
    ), {"colors": palette, "frames": composition.frames, "fps": composition.fps, "font": family}
