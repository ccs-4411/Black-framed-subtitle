import os
import sys
import subprocess
import shutil
import re
import gradio as gr

# =====================================================================
# 🛠️ 環境修復：自動偵測並強制修復 FFmpeg 執行路徑
# =====================================================================
FFMPEG_PATH = shutil.which("ffmpeg")
if not FFMPEG_PATH:
    if os.path.exists("/usr/bin/ffmpeg"):
        FFMPEG_PATH = "/usr/bin/ffmpeg"
    elif os.path.exists("/usr/local/bin/ffmpeg"):
        FFMPEG_PATH = "/usr/local/bin/ffmpeg"
    else:
        FFMPEG_PATH = "ffmpeg"

print(f"📡 系統確認 FFmpeg 核心路徑: {FFMPEG_PATH}")

# =====================================================================
# 📝 字幕高級解析：根據 UI 參數動態產生中英文 ASS 樣式
# =====================================================================
def srt_to_ass(srt_path, ass_path, zh_font, zh_bold, zh_italic, zh_size, zh_color, en_font, en_bold, en_italic, en_size, en_color, v_offset):
    """將 SRT 字幕轉換為動態對齊 UI 參數的中英文獨立樣式 ASS"""
    if not os.path.exists(srt_path):
        return False
        
    def convert_color(hex_str):
        if not hex_str or not hex_str.startswith("#"):
            return "FFFFFF"
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 6:
            r, g, b = hex_str[0:2], hex_str[2:4], hex_str[4:6]
            return f"{b}{g}{r}"
        return "FFFFFF"

    ass_zh_color = convert_color(zh_color)
    ass_en_color = convert_color(en_color)
    
    b_zh = "1" if zh_bold else "0"
    i_zh = "1" if zh_italic else "0"
    b_en = "1" if en_bold else "0"
    i_en = "1" if en_italic else "0"

    margin_v_zh = max(1, 25 + v_offset)
    margin_v_en = max(1, 5 + v_offset)

    ass_header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 854\n"
        "PlayResY: 480\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{zh_font},{zh_size},&H00{ass_zh_color},&H000000FF,&H00000000,&H00000000,{b_zh},{i_zh},0,0,100,100,0,0,1,0,0,2,10,10,{margin_v_zh},1\n"
        f"Style: SubTitle,{en_font},{en_size},&H00{ass_en_color},&H000000FF,&H00000000,&H00000000,{b_en},{i_en},0,0,100,100,0,0,1,0,0,2,10,10,{margin_v_en},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    
    with open(srt_path, "r", encoding="utf-8") as f:
        srt_content = f.read()
        
    blocks = re.split(r'\n\s*\n', srt_content.strip())
    ass_lines = []
    
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            time_line = lines[1]
            text_lines = [l.strip() for l in lines[2:] if l.strip()]
            
            match = re.match(r'(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)', time_line)
            if match:
                g = match.groups()
                start_ass = f"{int(g[0])}:{g[1]}:{g[2]}.{int(g[3])//10:02d}"
                end_ass = f"{int(g[4])}:{g[5]}:{g[6]}.{int(g[7])//10:02d}"
                
                if len(text_lines) >= 2:
                    main_text = re.sub(r'<[^>]+>', '', text_lines[0])
                    sub_text = re.sub(r'<[^>]+>', '', text_lines[1])
                    full_text = f"{main_text}\\N{{\\rSubTitle}}{sub_text}"
                else:
                    full_text = re.sub(r'<[^>]+>', '', text_lines[0]) if text_lines else ""
                
                ass_lines.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{full_text}")
                
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        f.write("\n".join(ass_lines))
    return True

# =====================================================================
# 🎬 影音控制：動態結合解析度、黑框高度與中英文字幕控制
# =====================================================================
def process_video_task(
    video_input, subtitle_input, 
    resolution, pad_height, v_offset,
    zh_font, zh_bold, zh_italic, zh_size, zh_color,
    en_font, en_bold, en_italic, en_size, en_color,
    mode="preview", progress=gr.Progress()
):
    if not video_input or not subtitle_input:
        return None, "❌ 請先上傳影片檔案與字幕檔案！"
        
    mode_text = "10秒動態預覽" if mode == "preview" else "全片完整轉檔"
    progress(0, desc=f"🚀 正在配置 [{mode_text}] 進階環境...")
    
    current_dir = os.path.abspath(os.path.dirname(__file__))
    output_filename = "preview_subtitled.mp4" if mode == "preview" else "full_subtitled.mp4"
    output_video = os.path.join(current_dir, output_filename)
    preview_ass = os.path.join(current_dir, "render_temp.ass")
    
    if os.path.exists(output_video):
        os.remove(output_video)
    if os.path.exists(preview_ass):
        os.remove(preview_ass)
        
    if not srt_to_ass(subtitle_input, preview_ass, zh_font, zh_bold, zh_italic, zh_size, zh_color, en_font, en_bold, en_italic, en_size, en_color, v_offset):
        return None, "❌ 字幕樣式編譯失敗。"
        
    escaped_ass_path = preview_ass.replace(":", "\\:").replace("/", "\\/")
    subtitles_filter = f"subtitles='{escaped_ass_path}'"
    
    if resolution == "854x480":
        total_height = 480 + pad_height
        vf_chain = f"scale=854:480,pad=854:{total_height}:0:0:black,{subtitles_filter}"
    elif resolution == "1280x720":
        total_height = 720 + pad_height
        vf_chain = f"scale=1280:720,pad=1280:{total_height}:0:0:black,{subtitles_filter}"
    else:
        vf_chain = f"scale=854:-2,{subtitles_filter}"
    
    cmd = [FFMPEG_PATH, "-y", "-threads", "2"]
    if mode == "preview":
        cmd.extend(["-ss", "00:00:00", "-t", "10"])
        
    cmd.extend([
        "-i", video_input,
        "-vf", vf_chain,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-c:a", "aac",
        output_video
    ])
    
    log_msg = f"⚙️ UI 參數同步成功！\n📺 解析度: {resolution} | 黑框增高: {pad_height}px | 垂直位移: {v_offset}px\n"
    progress(0.5, desc=f"🎬 FFmpeg 正在進行 [{mode_text}] 渲染中...")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if os.path.exists(output_video) and os.path.getsize(output_video) > 0:
            return output_video, log_msg + f"🎉 [{mode_text}] 處理完成！請在上方放大版播放器檢視成果。"
        else:
            return None, log_msg + f"❌ 轉檔失敗。\n{result.stderr}"
    except subprocess.CalledProcessError as e:
        return None, log_msg + f"💥 FFmpeg 執行失敗！\n{e.stderr}"

# =====================================================================
# 🎨 介面佈局：大影片、小日誌優化版面
# =====================================================================
with gr.Blocks(theme=gr.themes.Soft(primary_hue="teal", secondary_hue="slate")) as demo:
    gr.Markdown("# 🎬 Python Video Toolbox v11.2 (視覺優化版)")
    
    with gr.Row():
        # 左側控制面板 (佔比維持 1)
        with gr.Column(scale=1):
            gr.Markdown("### 📂 1. 檔案來源")
            video_file = gr.File(label="選擇原始影片 (MP4)", file_types=[".mp4"])
            subtitle_file = gr.File(label="選擇字幕檔案 (SRT)", file_types=[".srt"])
            
            with gr.Group():
                gr.Markdown("### 📺 【解析度與黑框邊界】")
                res_select = gr.Dropdown(choices=["854x480", "1280x720", "原始比例"], value="854x480", label="解析度")
                pad_slider = gr.Slider(minimum=0, maximum=800, value=95, step=1, label="黑框高度 (px)")
                offset_slider = gr.Slider(minimum=-300, maximum=300, value=0, step=1, label="垂直位移 (對底邊 px)")
            
            with gr.Group():
                gr.Markdown("### 🔤 【中文字型樣式】")
                zh_font_dropdown = gr.Dropdown(choices=["WenQuanYi Zen Hei", "Arial", "Noto Sans CJK TC"], value="WenQuanYi Zen Hei", label="中文字型")
                with gr.Row():
                    zh_b = gr.Checkbox(label="粗體", value=True)
                    zh_i = gr.Checkbox(label="斜體", value=False)
                with gr.Row():
                    zh_size_input = gr.Number(label="字體大小", value=44)
                    zh_color_input = gr.ColorPicker(label="字體顏色", value="#FFFFFF")
            
            with gr.Group():
                gr.Markdown("### 🔤 【英文字型樣式】")
                en_font_dropdown = gr.Dropdown(choices=["Arial", "Courier New", "Times New Roman"], value="Arial", label="英文字型")
                with gr.Row():
                    en_b = gr.Checkbox(label="粗體", value=False)
                    en_i = gr.Checkbox(label="斜體", value=True)
                with gr.Row():
                    en_size_input = gr.Number(label="字體大小", value=22)
                    en_color_input = gr.ColorPicker(label="字體顏色", value="#FFFF00")
            
            gr.Markdown("### ⚙️ 2. 工作流程")
            with gr.Row():
                btn_preview = gr.Button("🔄 生成 10 秒預覽", variant="secondary")
                btn_full = gr.Button("🚀 執行全片轉檔", variant="primary")
                
        # 右側輸出面板 (透過 scale=1.5 放大寬度，並讓日誌縮小)
        with gr.Column(scale=1.5):
            gr.Markdown("### 📺 3. 渲染成果預覽")
            # 透過限制高度讓播放器自適應放大，看字幕超精準
            video_output = gr.Video(label="雙語字幕加黑邊預覽播放器", interactive=False, height=520)
            
            gr.Markdown("### 📝 系統日誌")
            # 縮小日誌高度（lines=3），不再佔用大量垂直空間
            log_output = gr.Textbox(label="Console Log", placeholder="等待任務觸發...", lines=3, max_lines=4, autoscroll=True)

    # 參數打包傳遞 (移除上版的語法錯誤符號)
    input_components = [
        video_file, subtitle_file,
        res_select, pad_slider, offset_slider,
        zh_font_dropdown, zh_b, zh_i, zh_size_input, zh_color_input,
        en_font_dropdown, en_b, en_i, en_size_input, en_color_input
    ]

    btn_preview.click(fn=lambda *args: process_video_task(*args, mode="preview"), inputs=input_components, outputs=[video_output, log_output])
    btn_full.click(fn=lambda *args: process_video_task(*args, mode="full"), inputs=input_components, outputs=[video_output, log_output])

if __name__ == "__main__":
    demo.launch()
