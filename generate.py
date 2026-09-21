import asyncio, html, json, os, re, subprocess
from pathlib import Path
from datetime import date
import edge_tts, requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).parent
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)
COUNT = int(os.getenv("SHORTS_COUNT", "1"))
VOICE = os.getenv("SHORTS_VOICE", "en-US-AriaNeural")
UA = {"User-Agent": "YouTubeShortsAutomation/1.1 (educational video generator)"}

def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/" + name, size)

def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]

def clean_html(value):
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()

def commons_image(query, destination):
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": 10,
        "prop": "imageinfo", "iiprop": "url|mime|extmetadata", "iiurlwidth": 1400,
    }
    data = requests.get(api, params=params, headers=UA, timeout=45).json()
    pages = data.get("query", {}).get("pages", {})
    allowed = ("public domain", "cc0", "cc by", "cc-by")
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        meta = info.get("extmetadata", {})
        license_name = clean_html(meta.get("LicenseShortName", {}).get("value", ""))
        if mime not in ("image/jpeg", "image/png") or not any(x in license_name.lower() for x in allowed):
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        response = requests.get(url, headers=UA, timeout=60)
        response.raise_for_status()
        destination.write_bytes(response.content)
        artist = clean_html(meta.get("Artist", {}).get("value", "Wikimedia Commons contributor"))
        credit = clean_html(meta.get("Credit", {}).get("value", ""))
        return {
            "page": info.get("descriptionurl", "https://commons.wikimedia.org"),
            "artist": artist[:180], "license": license_name, "credit": credit[:180],
        }
    return None

def fallback_image(path, index):
    colors = [(18, 35, 58), (50, 24, 56), (13, 54, 55), (66, 35, 20)]
    im = Image.new("RGB", (900, 1600), colors[index % len(colors)])
    d = ImageDraw.Draw(im)
    for y in range(1600):
        shade = int(65 * y / 1600)
        d.line((0, y, 900, y), fill=tuple(min(255, c + shade) for c in colors[index % len(colors)]))
    for x, y, r in [(130,240,90),(730,390,140),(270,1050,180),(760,1280,110)]:
        d.ellipse((x-r,y-r,x+r,y+r), fill=(255,190,65))
    im = im.filter(ImageFilter.GaussianBlur(40))
    im.save(path, quality=93)

def make_background(source, destination):
    with Image.open(source) as original:
        im = ImageOps.fit(original.convert("RGB"), (900, 1600), method=Image.Resampling.LANCZOS)
    im = ImageEnhance.Contrast(im).enhance(1.08)
    dark = Image.new("RGBA", im.size, (0, 0, 0, 75))
    im = Image.alpha_composite(im.convert("RGBA"), dark).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((42, 55, 365, 116), 25, fill=(8, 10, 15, 205))
    d.text((66, 69), "STRANGE BUT TRUE", font=font(27, True), fill=(255, 211, 84))
    d.rounded_rectangle((42, 1450, 858, 1530), 25, fill=(5, 7, 12, 180))
    d.text((450, 1474), "FOLLOW FOR ANOTHER TRUE STORY", anchor="mm", font=font(25, True), fill="white")
    im.save(destination, quality=94)

def ass_time(seconds):
    cs = max(0, int(seconds * 100))
    return f"{cs//360000}:{(cs//6000)%60:02}:{(cs//100)%60:02}.{cs%100:02}"

def caption_chunks(text):
    words = text.split()
    chunks, current = [], []
    for word in words:
        current.append(word)
        if len(current) >= 5 or (len(current) >= 3 and word.endswith((".", "!", "?", ","))):
            chunks.append(" ".join(current)); current = []
    if current:
        chunks.append(" ".join(current))
    return chunks

def write_ass(text, duration, path):
    chunks = caption_chunks(text)
    step = duration / max(1, len(chunks))
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,DejaVu Sans,52,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,3,3,0,2,55,55,185,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []
    for i, chunk in enumerate(chunks):
        safe = chunk.replace("{", "(").replace("}", ")")
        events.append(f"Dialogue: 0,{ass_time(i*step)},{ass_time(min(duration,(i+1)*step))},Caption,,0,0,0,,{safe}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")

async def speak(text, path):
    await edge_tts.Communicate(text, VOICE, rate="+4%", volume="+20%").save(str(path))

def media_duration(path):
    result = subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())

def render(item, index):
    name = f"{index+1:02}-{slug(item['title'])}"
    raw = OUT / f"{name}-source.jpg"
    background = OUT / f"{name}-background.jpg"
    audio = OUT / f"{name}.mp3"
    captions = OUT / f"{name}.ass"
    video = OUT / f"{name}.mp4"

    attribution = commons_image(item.get("image_query", item["title"]), raw)
    if not attribution:
        fallback_image(raw, index)
    make_background(raw, background)

    asyncio.run(speak(item["script"], audio))
    audio_seconds = media_duration(audio)
    if audio_seconds < 2:
        raise RuntimeError("Narration audio was not generated correctly")
    write_ass(item["script"], audio_seconds, captions)

    ass_path = str(captions.resolve()).replace("\\", "/").replace(":", "\\:")
    video_filter = (
        "scale=800:1422,crop=720:1280,"
        "zoompan=z='min(zoom+0.00035,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        "d=1:s=720x1280:fps=30,"
        f"ass='{ass_path}',format=yuv420p"
    )
    subprocess.run([
        "ffmpeg","-y","-loop","1","-framerate","30","-i",str(background),"-i",str(audio),
        "-map","0:v:0","-map","1:a:0","-vf",video_filter,
        "-af","loudnorm=I=-16:LRA=7:TP=-1.5",
        "-c:v","libx264","-preset","veryfast","-crf","23",
        "-c:a","aac","-b:a","160k","-ar","48000",
        "-t",f"{audio_seconds:.3f}","-movflags","+faststart",str(video)
    ], check=True)
    probe = subprocess.run(
        ["ffprobe","-v","error","-select_streams","a","-show_entries","stream=codec_name","-of","csv=p=0",str(video)],
        check=True, capture_output=True, text=True,
    )
    if "aac" not in probe.stdout:
        raise RuntimeError("Final video has no audio stream")
    return video, attribution

def send(video, item, index, attribution):
    url = os.getenv("MAKE_WEBHOOK_URL")
    if not url:
        return
    image_credit = ""
    if attribution:
        image_credit = f"\nImage: {attribution['artist']} — {attribution['license']}\n{attribution['page']}"
    description = f"{item['script']}\n\nFact source: {item['source']}{image_credit}\n\n#shorts #facts #history"
    with video.open("rb") as f:
        response = requests.post(
            url,
            data={"title":item["title"][:100],"description":description,"filename":video.name,
                  "position":str(index+1),"publish_date":date.today().isoformat()},
            files={"video":(video.name,f,"video/mp4")}, timeout=240,
        )
    response.raise_for_status()

def main():
    items = json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))[:COUNT]
    manifest = []
    for i, item in enumerate(items):
        video, attribution = render(item, i)
        send(video, item, i, attribution)
        manifest.append({**item, "file":video.name, "image_attribution":attribution})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Created {len(manifest)} Shorts with verified audio streams")

if __name__ == "__main__":
    main()
