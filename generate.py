import asyncio, json, os, re, subprocess
from pathlib import Path
from datetime import date
import edge_tts, requests
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).parent
OUT=ROOT/"output"
OUT.mkdir(exist_ok=True)
COUNT=int(os.getenv("SHORTS_COUNT","1"))
VOICE=os.getenv("SHORTS_VOICE","en-US-AriaNeural")

def font(size,bold=False):
    p="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(p,size)

def wrap(draw,text,fnt,width):
    lines=[]; current=""
    for word in text.split():
        trial=(current+" "+word).strip()
        if draw.textbbox((0,0),trial,font=fnt)[2] <= width: current=trial
        else:
            if current: lines.append(current)
            current=word
    if current: lines.append(current)
    return lines

def slug(text):
    return re.sub(r"[^a-z0-9]+","-",text.lower()).strip("-")[:48]

def card(item,path,index):
    colors=[(18,24,38),(31,20,45),(12,44,47),(48,27,18),(23,37,62)]
    base=colors[index%len(colors)]
    im=Image.new("RGB",(720,1280),base); d=ImageDraw.Draw(im)
    for y in range(1280):
        add=int(35*y/1280)
        d.line((0,y,720,y),fill=tuple(min(255,c+add) for c in base))
    d.rounded_rectangle((44,180,676,1070),38,fill=(8,11,18),outline=(255,197,71),width=4)
    d.text((60,70),"ONE STRANGE TRUE STORY",font=font(29,True),fill=(255,197,71))
    f=font(56,True); lines=wrap(d,item["hook"],f,570)
    heights=[d.textbbox((0,0),x,font=f)[3]+16 for x in lines]
    y=480-sum(heights)//2
    for line,h in zip(lines,heights):
        box=d.textbbox((0,0),line,font=f)
        d.text(((720-(box[2]-box[0]))/2,y),line,font=f,fill="white")
        y+=h
    d.text((60,1125),"The full story starts now",font=font(31,True),fill=(225,230,238))
    im.save(path,quality=94)

def stamp(seconds):
    ms=int((seconds%1)*1000); whole=int(seconds)
    return f"{whole//3600:02}:{(whole%3600)//60:02}:{whole%60:02},{ms:03}"

def subtitles(text,duration,path):
    words=text.split(); groups=[words[i:i+7] for i in range(0,len(words),7)]
    step=duration/max(1,len(groups)); blocks=[]
    for i,g in enumerate(groups):
        blocks.append(f"{i+1}\n{stamp(i*step)} --> {stamp(min(duration,(i+1)*step))}\n{' '.join(g)}\n")
    path.write_text("\n".join(blocks),encoding="utf-8")

async def speak(text,path):
    await edge_tts.Communicate(text,VOICE,rate="+8%").save(str(path))

def duration(path):
    r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],check=True,capture_output=True,text=True)
    return float(r.stdout.strip())

def render(item,index):
    name=f"{index+1:02}-{slug(item['title'])}"
    image=OUT/f"{name}.jpg"; audio=OUT/f"{name}.mp3"; srt=OUT/f"{name}.srt"; video=OUT/f"{name}.mp4"
    card(item,image,index)
    asyncio.run(speak(item["script"],audio))
    subtitles(item["script"],duration(audio),srt)
    sub=str(srt).replace("\\","/").replace(":","\\:")
    style="FontName=DejaVu Sans,FontSize=22,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=3,Alignment=2,MarginV=120"
    subprocess.run(["ffmpeg","-y","-loop","1","-i",str(image),"-i",str(audio),"-vf",f"scale=720:1280,format=yuv420p,subtitles='{sub}':force_style='{style}'","-c:v","libx264","-preset","veryfast","-b:v","900k","-c:a","aac","-b:a","96k","-shortest","-movflags","+faststart",str(video)],check=True)
    return video

def send(video,item,index):
    url=os.getenv("MAKE_WEBHOOK_URL")
    if not url: return
    desc=f"{item['script']}\n\nSource: {item['source']}\n\n#shorts #facts #history"
    with video.open("rb") as f:
        r=requests.post(url,data={"title":item["title"][:100],"description":desc,"filename":video.name,"position":str(index+1),"publish_date":date.today().isoformat()},files={"video":(video.name,f,"video/mp4")},timeout=180)
    r.raise_for_status()

def main():
    items=json.loads((ROOT/"topics.json").read_text(encoding="utf-8"))[:COUNT]
    manifest=[]
    for i,item in enumerate(items):
        video=render(item,i); send(video,item,i)
        manifest.append({**item,"file":video.name})
    (OUT/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(f"Created {len(manifest)} Shorts")

if __name__=="__main__":
    main()
