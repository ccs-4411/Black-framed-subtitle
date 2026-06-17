import os
import re
import glob
import subprocess
import gradio as gr

# --- 測試檔案暫存路徑 ---
TEST_VIDEO = "test_video.mp4"
TEST_SRT = "test_subtitles.srt"

# ==========================================
# 【核心邏輯：時間與顏色轉換】
# ==========================================
def str_to_sec(s):
    try:
        s = s.replace(',', '.')
        parts = s.split(':')
        if len(parts) == 3:
            h, m, sec = parts
            return int(h) * 3600 + int(m) * 60 + float(sec)
        elif len(parts) == 2:
            m, sec = parts
            return int(m) * 60 + float(sec)
        return float(s)
    except Exception as e:
        print(f"⚠️ 時間解析失敗 ({s}): {e}")
        return 0.0

def sec_to_ass_time(seconds):
    if seconds < 0: 
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    # ASS 規範的時間格式為 H:MM:SS.CC (小數點後兩位)
    return f"{h:01d}:{m:02d}:{s:05.2f}"

def hex_to_ass_color(hex_str):
    if not hex_str:
        return "&H00FFFFFF"
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 6:
        r, g, b = hex_str[0:2], hex_str[2:4], hex_str[4:6]
        # ASS 使用 AGBR 格式：&H[邊欄透明度][藍][綠][紅]
        return f"&H00{b}{g}{r}"
    return "&H00FFFFFF"

# ==========================================
# 【自動縮放 UI 數值連動】
# ==========================================
def on_resolution_change(res_text):
    try:
        current_h = int(res_text.split('x')[1])
        base_h = 1080
        ratio = current_h / base_h
        
        # 根據解析度動態計算初始推薦值
        new_zh = int(100 * ratio)
        new_en = int(50 * ratio)
        new_pad = int(220 * ratio)
        
        return gr.update(value=new_zh), gr.update(value=new_en), gr.update(value=new_pad)
    except:
        return gr.update(), gr.update(), gr.update()

# ==========================================
# 【核心：上傳檔案真實路徑提取器】
# ==========================================
def get_real_path(file_obj):
    if not file_obj:
        return None
        
    path = None
    if isinstance(file_obj, str):
        path = file_obj
    elif isinstance(file_obj, dict) and 'name' in file_obj:
        path = file_obj['name']
    else:
        path = getattr(file_obj, 'name', None)
        
    # 如果路徑異常或檔案不存在，強制肉搜暫存目錄
    if not path or "temp_auto_compressed" in path or not os.path.exists(path):
        print("🕵️ 偵測到異常快取干擾，啟動全硬碟真實原檔肉搜...")
        found_files = glob.glob("/tmp/gradio/*/*.mp4") + glob.glob("/tmp/gradio/*/*.mkv") + glob.glob("**/gradio/*")
        if found_files:
            found_files.sort(key=lambda x: os.path.getsize(x), reverse=True)
            for f in found_files:
                if "temp_auto_compressed" not in f and os.path.isfile(f):
                    return f
    return path

# ==========================================
# 【核心：上傳檔案引導提示】
# ==========================================
def auto_pre_compress(video):
    real_path = get_real_path(video)
    if not real_path or not os.path.exists(real_path):
        return "❌ 錯誤：無法鎖定實體影片位置，請確認網頁上傳進度已達 100%。"
    
    file_size_mb = os.path.getsize(real_path) / (1024 * 1024)
    return f"⚡【系統提示】原始大影片已 100% 寫入雲端硬碟（大小: {file_size_mb:.1f} MB）！實體路徑已牢牢鎖定。現在您可以放心地反覆點擊「10秒預覽」或「開始全片轉檔任務」。"

# ==========================================
# 【一鍵載入測試檔案】
# ==========================================
def load_test_files():
    v_path = TEST_VIDEO if os.path.exists(TEST_VIDEO) else None
    s_path = TEST_SRT if os.path.exists(TEST_SRT) else None
    
    msg = "【系統提示】已成功載入內建測試檔案！"
    if not v_path or not s_path:
        msg = "⚠️ 提示：空間內未偵測到 test_video.mp4 或 test_subtitles.srt。"
        
    return v_path, s_path, msg

# ==========================================
# 【生成 ASS 字幕檔】
# ==========================================
def create_ass_file(srt_path, res_w, res_h, pad_h, pos_y, font_zh, font_en, zh_size, en_size, color_zh, color_en, zh_bold, zh_italic, en_bold, en_italic, preview_mode=False):
    temp_ass = "preview_render.ass" if preview_mode else "full_render.ass"
    ratio = res_h / 1080.0
    
    # 底部加了 pad_h 的黑框，ASS 畫布總高度變為 res_h + pad_h
    # 對齊方式 2 (底部正中) 的 MarginV 是從「新畫布的最底端」往上計算
    m_v = int((pad_h / 2) + pos_y)
    if m_v < 0: m_v = 0
    zh_margin = m_v + int(en_size) + int(15 * ratio)
    
    ass_c_zh = hex_to_ass_color(color_zh)
    ass_c_en = hex_to_ass_color(color_en)
    
    z_b = -1 if zh_bold else 0
    z_i = -1 if zh_italic else 0
    e_b = -1 if en_bold else 0
    e_i = -1 if en_italic else 0
    
    # 符合 ASS 標準的格式定義
    header = f"[Script Info]\nScriptType: v4.00+\nPlayResX: {res_w}\nPlayResY: {res_h+pad_h}\nScaledBorderAndShadow: yes\n\n"
    header += "[v4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    header += f"Style: ZH,{font_zh},{zh_size},{ass_c_zh},&H00000000,&H00000000,&H00000000,{z_b},{z_i},0,0,100,100,0,0,1,2,0,2,10,10,{zh_margin},1\n"
    header += f"Style: EN,{font_en},{en_size},{ass_c_en},&H00000000,&H00000000,&H00000000,{e_b},{e_i},0,0,100,100,0,0,1,2,0,2,10,10,{m_v},1\n\n"
    header += "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    
    if not srt_path or not os.path.exists(srt_path):
        with open(temp_ass, "w", encoding="utf-8-sig") as f: 
            f.write(header)
        return temp_ass
        
    try:
        with open(srt_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        
        blocks = re.split(r'\n\s*\n', content.replace('\r\n', '\n').strip())
        
        for b in blocks:
            lines = [x.strip() for x in b.split('\n') if x.strip()]
            if len(lines) >= 3:
                m = re.findall(r"(\d+:\d+:\d+[,.]\d+)", lines[1])
                if m and len(m) >= 2:
                    s_s, e_s = str_to_sec(m[0]), str_to_sec(m[1])
                    
                    if preview_mode and s_s > 10.0:
                        continue
                        
                    s_t, e_t = sec_to_ass_time(s_s), sec_to_ass_time(e_s)
                    text_content = " ".join(lines[2:])
                    
                    # 精準分離中文與英文
                    if re.search(r'[\u4e00-\u9fff]', text_content):
                        chi = " ".join([t for t in text_content.split() if re.search(r'[\u4e00-\u9fff]', t)])
                        eng = " ".join([t for t in text_content.split() if not re.search(r'[\u4e00-\u9fff]', t)])
                        if not chi: chi = text_content
                    else:
                        chi = ""
                        eng = text_content

                    if not chi and text_content: 
                        chi = text_content
                    
                    if chi: 
                        header += f"Dialogue: 0,{s_t},{e_t},ZH,,0,0,0,,{chi}\n"
                    if eng and eng != chi: 
                        header += f"Dialogue: 0,{s_t},{e_t},EN,,0,0,0,,{eng}\n"
                        
    except Exception as e:
        print(f"❌ SRT 轉 ASS 發生錯誤: {e}")
        
    with open(temp_ass, "w", encoding="utf-8-sig") as f:
        f.write(header)
    return temp_ass

# ==========================================
# 【核心：FFmpeg 轉檔/預覽處理中心】
# ==========================================
def process_video_task(video, srt, resolution, pad_height, pos_y, font_zh, font_en, zh_size, en_size, color_zh, color_en, zh_bold, zh_italic, en_bold, en_italic, mode="full"):
    if not video or not srt:
        return None, "❌ 錯誤：請先上傳影片與 SRT 字幕檔！"
        
    res_w, res_h = map(int, resolution.split('x'))

    working_video_path = get_real_path(video)
    srt_input_path = get_real_path(srt)
            
    if not working_video_path or not os.path.exists(working_video_path):
        return None, "❌ 錯誤：硬碟中找不到實體原始影片，請重新上傳。"
    
    is_preview = (mode == "preview")
    output_path = "preview_subtitled.mp4" if is_preview else "output_subtitled.mp4"
    
    if os.path.exists(output_path):
        try: 
            os.remove(output_path)
        except:
            if not is_preview:
                output_path = f"output_subtitled_{os.getpid()}.mp4"
                
    safe_ass_path = os.path.abspath(create_ass_file(
        srt_input_path, 
        res_w, res_h, pad_height, pos_y, 
        font_zh, font_en, int(zh_size), int(en_size), 
        color_zh, color_en, zh_bold, zh_italic, en_bold, en_italic,
        preview_mode=is_preview
    ))
    
    # 針對 FFmpeg 濾鏡進行跨平台路徑特殊字元轉義，防止路徑崩潰
    cleaned_ass_path = safe_ass_path.replace("\\", "/").replace(":", "\\:")
    
    cmd = ["ffmpeg", "-y", "-threads", "2"]
    
    if is_preview:
        cmd += ["-ss", "00:00:00", "-t", "10", "-i", working_video_path]
    else:
        cmd += ["-i", working_video_path]
        
    cmd += ["-vf", f"scale={res_w}:{res_h},pad={res_w}:{res_h+pad_height}:0:0:black,subtitles='{cleaned_ass_path}'"]
           
    if is_preview:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-c:a", "aac", output_path]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", output_path]
    
    print(f"🎬 執行指令: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0 and os.path.exists(output_path):
        if is_preview:
            return output_path, "🔄 10 秒動態效果預覽生成成功！現在您可以反覆微調參數，或直接啟動全片轉檔。"
        else:
            return output_path, "✨ 全片轉檔成功！"
    else:
        return None, f"❌ 轉檔發生異常中止。\n錯誤日誌：\n{result.stderr}"

# ==========================================
# 【自訂美化 CSS 樣式表】
# ==========================================
custom_css = """
span, label, p, .text-sm, .gr-form label { font-size: 16px !important; font-weight: 800 !important; color: #2c3e50 !important; }
input, select, textarea { font-size: 15px !important; font-weight: bold !important; }
h3, h4 { font-size: 18px !important; font-weight: 900 !important; margin-top: 5px !important; color: #1a1a1a !important; }
.video-container { height: 500px !important; }
.log-box textarea { background-color: #1a1a1a !important; color: #4af626 !important; font-family: monospace !important; font-size: 14px !important; }
#btn_preview { background: linear-gradient(135deg, #3498db, #2980b9) !important; color: white !important; font-weight: bold !important; }
#btn_run { background: linear-gradient(135deg, #27ae60, #219653) !important; color: white !important; font-weight: bold !important; }
.gr-group { border: 1px solid #bdc3c7 !important; border-radius: 8px !important; padding: 12px !important; background-color: #fcfcfc !important; }
"""

# Gradio 6.0 規範：css 參數從 Blocks 移到了 launch() 中
with gr.Blocks(title="Python Video Toolbox V9.6", fill_height=True) as demo:
    gr.Markdown("# 🎬 Python Video Toolbox V9.6 - Railway 雲端獨立版")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📁 【檔案選取與測試】")
            btn_test = gr.Button("🎯 一鍵載入測試檔案", variant="secondary")
            
            video_input = gr.File(label="1. 原始影片 (支援 .mp4, .mkv 大檔)", file_types=[".mp4", ".mkv"])
            srt_input = gr.File(label="2. 字幕檔案 (SRT)", file_types=[".srt"])
            
            gr.Markdown("### 📺 【解析度與黑框邊界】")
            resolution = gr.Dropdown(choices=["1920x1080", "1280x720", "854x480"], value="854x480", label="解析度")
            pad_height = gr.Slider(minimum=0, maximum=800, value=95, step=5, label="黑框高度 (px)")
            pos_y = gr.Slider(minimum=-300, maximum=300, value=0, step=5, label="垂直位移 (對底邊 px)")
            
            with gr.Group(elem_classes="gr-group"):
                gr.Markdown("#### 🔤 【中文字體樣式】")
                font_zh = gr.Dropdown(choices=["WenQuanYi Zen Hei", "Arial", "Microsoft JhengHei"], value="WenQuanYi Zen Hei", label="中文字型")
                with gr.Row():
                    zh_bold = gr.Checkbox(label="粗體", value=True)
                    zh_italic = gr.Checkbox(label="斜體", value=False)
                with gr.Row():
                    zh_size = gr.Number(value=44, label="字體大小")
                    color_zh = gr.ColorPicker(value="#FFFFFF", label="字體顏色")

            with gr.Group(elem_classes="gr-group"):
                gr.Markdown("#### 🔤 【英文字體樣式】")
                font_en = gr.Dropdown(choices=["Arial", "Times New Roman"], value="Arial", label="英文字型")
                with gr.Row():
                    en_bold = gr.Checkbox(label="粗體", value=False)
                    en_italic = gr.Checkbox(label="斜體", value=True)
                with gr.Row():
                    en_size = gr.Number(value=22, label="字體大小")
                    color_en = gr.ColorPicker(value="#FFFF00", label="字體顏色")
                    
            gr.Markdown("### 🚀 【功能執行】")
            btn_preview = gr.Button("🔄 循環生成 10 秒動態預覽", variant="secondary", elem_id="btn_preview")
            btn_run = gr.Button("🚀 開始全片轉檔任務", variant="primary", elem_id="btn_run")
            
        with gr.Column(scale=1):
            gr.Markdown("### 🖥️ 【實時狀態與成果預覽】")
            log_output = gr.Textbox(label="狀態與實時日誌監控", placeholder="等待任務啟動...", lines=3, elem_classes="log-box")
            video_output = gr.Video(label="🚀 2. 轉檔成果 / 預覽影片播放器", elem_classes="video-container")

    # 事件關係連動
    video_input.upload(fn=auto_pre_compress, inputs=[video_input], outputs=[log_output])
    resolution.change(fn=on_resolution_change, inputs=[resolution], outputs=[zh_size, en_size, pad_height])
    btn_test.click(fn=load_test_files, inputs=[], outputs=[video_input, srt_input, log_output])
    
    btn_preview.click(
        fn=lambda *args: process_video_task(*args, mode="preview"),
        inputs=[video_input, srt_input, resolution, pad_height, pos_y, font_zh, font_en, zh_size, en_size, color_zh, color_en, zh_bold, zh_italic, en_bold, en_italic],
        outputs=[video_output, log_output]
    )
    
    btn_run.click(
        fn=lambda *args: process_video_task(*args, mode="full"),
        inputs=[video_input, srt_input, resolution, pad_height, pos_y, font_zh, font_en, zh_size, en_size, color_zh, color_en, zh_bold, zh_italic, en_bold, en_italic],
        outputs=[video_output, log_output]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    # Gradio 6.0+ 正確寫法：把 css 移入 launch 內，並移除了 show_api
    demo.launch(
        server_name="0.0.0.0", 
        server_port=port, 
        max_file_size="2gb", 
        css=custom_css
    )
