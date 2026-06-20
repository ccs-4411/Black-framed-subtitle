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
# 🔄 UI 連動核心邏輯
# =====================================================================
def update_ui_components(resolution):
    if resolution == "1920x1080":
        return (
            gr.update(maximum=1800, value=215, label="黑框高度 (1080p 最佳 px)"),
            gr.update(minimum=-600, maximum=600, value=0, label="垂直位移 (1080p 基準 px)"),
            gr.update(value=99),
            gr.update(value=50)
        )
    elif resolution == "1280x720":
        return (
            gr.update(maximum=1200, value=142, label="黑框高度 (720p 最佳 px)"),
            gr.update(minimum=-450, maximum=450, value=0, label="垂直位移 (720p 基準 px)"),
            gr.update(value=66),
            gr.update(value=33)
        )
    else:
        return (
            gr.update(maximum=800, value=95, label="黑框高度 (480p 基準 px)"),
            gr.update(minimum=-300, maximum=300, value=0, label="垂直位移 (480p 基準 px)"),
            gr.update(value=44),
            gr.update(value=22)
        )

# =====================================================================
# 📝 字幕高級解析
# =====================================================================
def srt_to_ass(srt_path, ass_path, zh_font, zh_bold, zh_italic, zh_size, zh_color, en_font, en_bold, en_italic, en_size, en_color, v_offset, resolution):
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

    if resolution == "1920x1080":
        play_res_x, play_res_y = "1920", "1080"
        margin_v_zh = max(1, 56 + int(v_offset))
        margin_v_en = max(1, 11 + int(v_offset))
    elif resolution == "1280x720":
        play_res_x, play_res_y = "1280", "720"
        margin_v_zh = max(1, 38 + int(v_offset))
        margin_v_en = max(1, 8 + int(v_offset))
    else:
        play_res_x, play_res_y = "854", "480"
        margin_v_zh = max(1, 25 + int(v_offset))
        margin_v_en = max(1, 5 + int(v_offset))

    ass_header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{zh_font},{int(zh_size)},&H00{ass_zh_color},&H000000FF,&H00000000,&H00000000,{b_zh},{i_zh},0,0,100,100,0,0,1,0,0,2,10,10,{margin_v_zh},1\n"
        f"Style: SubTitle,{en_font},{int(en_size)},&H00{ass_en_color},&H000000FF,&H00000000,&H00000000,{b_en},{i_en},0,0,100,100,0,0,1,0,0,2,10,10,{margin_v_en},1\n\n"
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
# 🎬 影音控制
# =====================================================================
def process_video_task(
    video_input, subtitle_input, 
    resolution, pad_height, v_offset,
    zh_font, zh_bold, zh_italic, zh_size, zh_color,
    en_font, en_bold, en_italic, en_size, en_color,
    preview_start_minutes,
    mode="preview", 
    progress=gr.Progress()
):
    if not video_input or not subtitle_input:
        return None, "❌ 請先上傳影片檔案與字幕檔案！"
        
    mode_text = "10秒動態預覽" if mode == "preview" else "全片完整轉檔"
    progress(0, desc=f"🚀 正在配置影音處理畫布...")
    
    if resolution == "1920x1080":
        total_height = 1080 + int(pad_height)
        scale_cmd = "scale=1920:1080"
        pad_cmd = f"pad=1920:{total_height}:0:0:black"
    elif resolution == "1280x720":
        total_height = 720 + int(pad_height)
        scale_cmd = "scale=1280:720"
        pad_cmd = f"pad=1280:{total_height}:0:0:black"
    elif resolution == "854x480":
        total_height = 480 + int(pad_height)
        scale_cmd = "scale=854:480"
        pad_cmd = f"pad=854:{total_height}:0:0:black"
    else:
        scale_cmd = "scale=854:-2"
        pad_cmd = ""

    current_dir = os.path.abspath(os.path.dirname(__file__))
    output_filename = "preview_subtitled.mp4" if mode == "preview" else "full_subtitled.mp4"
    output_video = os.path.join(current_dir, output_filename)
    preview_ass = os.path.join(current_dir, "render_temp.ass")
    
    if os.path.exists(output_video):
        os.remove(output_video)
    if os.path.exists(preview_ass):
        os.remove(preview_ass)
        
    if not srt_to_ass(subtitle_input, preview_ass, zh_font, zh_bold, zh_italic, zh_size, zh_color, en_font, en_bold, en_italic, en_size, en_color, v_offset, resolution):
        return None, "❌ 字幕樣式編譯失敗。"
        
    escaped_ass_path = preview_ass.replace(":", "\\:").replace("/", "\\/")
    subtitles_filter = f"subtitles='{escaped_ass_path}'"
    
    vf_chain = f"{scale_cmd},{pad_cmd},{subtitles_filter}" if pad_cmd else f"{scale_cmd},{subtitles_filter}"
    
    cmd = [FFMPEG_PATH, "-y", "-threads", "2"]
    cmd.extend(["-i", video_input])
    
    if mode == "preview":
        mins = int(preview_start_minutes) if preview_start_minutes is not None and preview_start_minutes != "" else 0
        hh = mins // 60
        mm = mins % 60
        ss = 0
        start_time = f"{hh:02d}:{mm:02d}:{ss:02d}"
        cmd.extend(["-ss", start_time, "-t", "10"])
        
    cmd.extend([
        "-vf", vf_chain,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-c:a", "aac",
        output_video
    ])
    
    cmd_str = " ".join(cmd)
    log_msg = f"⚙️ 執行指令：\n{cmd_str}\n\n"
    log_msg += f"📺 輸出模式: {resolution}\n📏 實際黑框增高像素: {pad_height}px | 實際中文字體: {zh_size}px\n"
    if mode == "preview":
        log_msg += f"⏱️ 預覽起始時間: {start_time}\n"
    progress(0.5, desc=f"🎬 FFmpeg 正在進行 [{mode_text}] 渲染中...")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if os.path.exists(output_video) and os.path.getsize(output_video) > 0:
            return output_video, log_msg + f"🎉 [{mode_text}] 處理完成！請觀看右側放大版播放器檢視黑邊細節。"
        else:
            return None, log_msg + f"❌ 轉檔失敗。\n{result.stderr}"
    except subprocess.CalledProcessError as e:
        return None, log_msg + f"💥 FFmpeg 執行失敗！\n{e.stderr}"

# =====================================================================
# 🎨 自訂 CSS 樣式
# =====================================================================
custom_css = """
/* 所有表單元件字體 12pt */
body, .gradio-container, .gradio-app, .gradio-row, .gradio-column, 
label, span, p, div, input, select, textarea, button,
.gr-button, .gr-form-label, .gr-file-label, .gr-textbox, 
.accordion-label, h3, .gr-markdown h3 {
    font-size: 12pt !important;
}

/* 標題 20pt 置中 */
.app-title {
    text-align: center;
    font-size: 20pt !important;
    font-weight: bold;
    color: #2c3e50;
    margin: 1.5rem 0 1rem 0;
    letter-spacing: 2px;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
}

/* 美化 */
.gr-group {
    border-radius: 12px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
    padding: 12px !important;
    background-color: #fafbfc !important;
}
.gr-accordion {
    border-radius: 12px !important;
    margin-bottom: 8px !important;
}
.gr-row {
    gap: 1.2rem !important;
}
.gr-column {
    padding: 0.8rem !important;
}
"""

# =====================================================================
# 🎨 介面佈局
# =====================================================================
with gr.Blocks(theme=gr.themes.Soft(primary_hue="teal", secondary_hue="slate"), css=custom_css) as demo:
    gr.HTML("<div class='app-title'>黑框影片與雙語字幕合併</div>")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📂 1. 檔案來源")
            video_file = gr.File(label="選擇原始影片 (MP4)", file_types=[".mp4"])
            subtitle_file = gr.File(label="選擇字幕檔案 (SRT)", file_types=[".srt"])
            
            with gr.Accordion("📐 解析度與黑框進階設定", open=False):
                with gr.Group():
                    gr.Markdown("### 📺 【解析度與黑框邊界】")
                    res_select = gr.Dropdown(choices=["854x480", "1280x720", "1920x1080", "原始比例"], value="854x480", label="解析度")
                    pad_slider = gr.Slider(minimum=0, maximum=800, value=95, step=1, label="黑框高度 (480p 基準 px)")
                    offset_slider = gr.Slider(minimum=-300, maximum=300, value=0, step=1, label="垂直位移 (480p 基準 px)")
            
            with gr.Row():
                btn_expand_subtitle = gr.Button("🎨 設定中外文字幕", variant="secondary")
            
            with gr.Accordion(label="🎨 中外文字幕樣式設定（點擊展開/收合）", open=False) as subtitle_accordion:
                with gr.Group():
                    gr.Markdown("### 🔤 【中文字型樣式】")
                    # 擴充中文字型選項
                    zh_font_dropdown = gr.Dropdown(
                        choices=[
                            "Noto Sans CJK TC", "Sans", "DejaVu Sans",
                            "標楷體", "新細明體", "微軟正黑體", "SimHei", "SimSun"
                        ],
                        value="Noto Sans CJK TC",
                        label="中文字型"
                    )
                    with gr.Row():
                        zh_b = gr.Checkbox(label="粗體", value=True)
                        zh_i = gr.Checkbox(label="斜體", value=False)
                    with gr.Row():
                        zh_size_input = gr.Number(label="中文字體大小 (px)", value=44)
                        zh_color_input = gr.ColorPicker(label="字體顏色", value="#FFFFFF")
                
                with gr.Group():
                    gr.Markdown("### 🔤 【英文字型樣式】")
                    # 擴充英文字型選項
                    en_font_dropdown = gr.Dropdown(
                        choices=[
                            "Arial", "Courier New", "Times New Roman",
                            "Segoe UI", "Tahoma", "Verdana", "Georgia"
                        ],
                        value="Arial",
                        label="英文字型"
                    )
                    with gr.Row():
                        en_b = gr.Checkbox(label="粗體", value=False)
                        en_i = gr.Checkbox(label="斜體", value=True)
                    with gr.Row():
                        en_size_input = gr.Number(label="英文字體大小 (px)", value=22)
                        en_color_input = gr.ColorPicker(label="字體顏色", value="#FFFF00")
            
            gr.Markdown("### ⚙️ 2. 工作流程")
            preview_start_input = gr.Number(label="預覽起始時間（分鐘）", value=5, precision=0, step=1, minimum=0)
            with gr.Row():
                btn_preview = gr.Button("🔄 生成 10 秒預覽", variant="secondary")
                btn_full = gr.Button("🚀 執行全片轉檔", variant="primary")
                
        with gr.Column(scale=1.5):
            gr.Markdown("### 📺 3. 渲染成果預覽")
            video_output = gr.Video(label="雙語字幕加黑邊預覽播放器", interactive=False, height=520)
            
            gr.Markdown("### 📝 系統日誌")
            log_output = gr.Textbox(label="Console Log", placeholder="等待任務觸發...", lines=5, max_lines=8, autoscroll=True)

    btn_expand_subtitle.click(
        fn=lambda: gr.update(open=True),
        outputs=[subtitle_accordion]
    )

    input_components = [
        video_file, subtitle_file,
        res_select, pad_slider, offset_slider,
        zh_font_dropdown, zh_b, zh_i, zh_size_input, zh_color_input,
        en_font_dropdown, en_b, en_i, en_size_input, en_color_input,
        preview_start_input
    ]

    res_select.change(
        fn=update_ui_components,
        inputs=[res_select],
        outputs=[pad_slider, offset_slider, zh_size_input, en_size_input]
    )

    btn_preview.click(
        fn=lambda *args: process_video_task(*args, mode="preview"),
        inputs=input_components,
        outputs=[video_output, log_output]
    )
    btn_full.click(
        fn=lambda *args: process_video_task(*args, mode="full"),
        inputs=input_components,
        outputs=[video_output, log_output]
    )

if __name__ == "__main__":
    demo.launch()
