import os
import uuid
import subprocess
import gradio as gr

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================
# 解析影片資訊（ffprobe）
# =========================
def get_resolution(video_path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        w, h = result.stdout.strip().split("x")
        return int(w), int(h)
    except:
        return 1280, 720  # fallback

# =========================
# 字幕尺寸規則
# =========================
def get_font_size(height):
    if height >= 1080:
        return 99, 50
    elif height >= 720:
        return 66, 33
    else:
        return 44, 22

# =========================
# SRT → ASS（核心）
# =========================
def srt_to_ass(srt_path, ass_path, font_size, font_size_en):
    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,20,1
Style: English,Arial,{font_size_en},&H00FFFFAA,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def time_to_ass(t):
        h, m, s = t.replace(",", ":").split(":")
        return f"{int(h)}:{int(m):02d}:{int(s):02d}.{int(s.split('.')[-1]) if '.' in s else 0:02d}"

    def parse_srt(srt):
        blocks = srt.strip().split("\n\n")
        events = []
        for b in blocks:
            lines = b.split("\n")
            if len(lines) >= 2:
                times = lines[1]
                start, end = times.split(" --> ")
                text = "\\N".join(lines[2:])
                events.append((start.strip(), end.strip(), text))
        return events

    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    events = parse_srt(content)

    body = ""
    for start, end, text in events:
        body += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header + body)

# =========================
# FFmpeg 燒錄字幕
# =========================
def burn_subtitle(video_path, ass_path, output_path):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", f"ass={ass_path}",
        "-c:a", "copy",
        output_path
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# =========================
# 主流程
# =========================
def process(video, srt):
    vid_id = str(uuid.uuid4())

    video_path = os.path.join(UPLOAD_DIR, vid_id + ".mp4")
    srt_path = os.path.join(UPLOAD_DIR, vid_id + ".srt")
    ass_path = os.path.join(UPLOAD_DIR, vid_id + ".ass")
    output_path = os.path.join(OUTPUT_DIR, vid_id + "_out.mp4")

    # 存檔
    with open(video_path, "wb") as f:
        f.write(video.read())

    with open(srt_path, "wb") as f:
        f.write(srt.read())

    # 解析解析度
    w, h = get_resolution(video_path)
    fs, fs_en = get_font_size(h)

    # SRT → ASS
    srt_to_ass(srt_path, ass_path, fs, fs_en)

    # 燒錄
    burn_subtitle(video_path, ass_path, output_path)

    return output_path

# =========================
# Web UI
# =========================
app = gr.Interface(
    fn=process,
    inputs=[
        gr.File(label="上傳影片"),
        gr.File(label="上傳 SRT 字幕")
    ],
    outputs=gr.File(label="輸出影片"),
    title="字幕燒錄工具 (自動解析度字幕大小版)"
)

if __name__ == "__main__":
    app.launch()
