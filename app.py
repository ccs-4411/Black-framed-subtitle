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
        h, m, sec = s.split(':')
        return int(h)*3600 + int(m)*60 + float(sec)
    except:
        return 0.0

def sec_to_ass_time(seconds):
    if seconds < 0: seconds = 0
    h, m = int(seconds // 3600), int((seconds % 3600) // 60)
    return f"{h:01d}:{m:02d}:{seconds % 60:05.2f}"

def hex_to_ass_color(hex_str):
    if not hex_str:
        return "&H00FFFFFF"
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 6:
        r, g, b = hex_str[0:2], hex_str[2:4], hex_str[4:6]
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
        
        new_zh = int(100 * ratio)
        new_en = int(50 * ratio)
        new_pad = int(220 * ratio)
        
        return new_zh, new_en, new_pad
    except:
        return 100, 50, 220

# ==========================================
# 【核心：上傳檔案真實路徑提取器】
# ==========================================
def get_real_path(video_obj):
    if not video_obj:
        return None
        
    path = None
    if isinstance(video_obj, str):
        path = video_obj
    elif isinstance(video_obj, dict) and 'name' in video_obj:
        path = video_obj['name']
    else:
        path = getattr(video_obj, 'name', None)
        
    # 💥【終極物理肉搜】如果 Gradio 變數不幸被舊快取污染（包含 temp_auto_compressed），立刻強制掃描硬碟
    if not path or "temp_auto_compressed" in path or not os.path.exists(path):
        print("🕵️ 偵測到異常路徑或舊快取干擾，啟動全硬碟真實原檔肉搜...")
        # 掃描 Gradio 的底層快取目錄
        found_files = glob.glob("/tmp/gradio/*/*.mp4") + glob.glob("/tmp/gradio/*/*.mkv")
        if found_files:
            # 依照檔案容量由大到小排序，精準抓取你上傳的真實原檔（排除任何損壞的 480p 殼檔）
            found_files.sort(key=lambda x: os.path.getsize(x), reverse=True)
            for f in found_files:
                if "temp_auto_compressed" not in f:
                    print(f"🎯 [物理防禦成功] 自動將輸入源導回真實大影片路徑: {f}")
                    return f
    return path

# ==========================================
# 【核心：上傳檔案引導提示】
# ==========================================
def auto_pre_compress(video):
    # 這裡純粹用來做實體檔案確認提示，100% 不在背景調用 ffmpeg 做任何自動壓縮
    real_path = get_real_path(video)
    if not real_path or not os.path.exists(real_path):
        return "❌ 錯誤：無法鎖定實體影片位置，請確認網頁上傳進度條已達 100%。"
    
    file_size_mb = os.path.getsize(real_path) / (1024 * 1024)
    return f"⚡【系統提示】原始大影片已 100% 寫入雲端硬碟（大小: {file_size_mb:.1f} MB）！實體路徑已牢牢鎖定。現在您可以放心地反覆點擊「5秒預覽」或「開始全片轉檔任務」。"

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
    
    m_v = int(pad_h / 2) + pos_y
    zh_margin = m_v + en_size + int(15 * ratio)
    
    ass_c_zh = hex_to_ass_color(color_zh)
    ass_c_en = hex_to_ass_color(color_en)
    
    z_b = 1 if zh_bold else 0
    z_i = 1 if zh_italic else 0
    e_b = 1 if en_bold else 0
    e_i = 1 if en_italic else 0
    
    header = f"[Script Info]\nPlayResX: {res_w}\nPlayResY: {res_h+pad_h}\nScaledBorderAndShadow: yes\n\n"
    header += "[v4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Bold, Italic, Alignment, MarginV, Outline, Shadow, BorderStyle\n"
    header += f"Style: ZH,{font_zh},{zh_size},{ass_c_zh},{z_b},{z_i},2,{zh_margin},2,0,1\n"
    header += f"Style: EN,{font_en},{en_size},{ass_c_en},{e_b},{e_i},2,{m_v},2,0,1\n\n"
    header += "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    
    if not srt_path:
        with open(temp_ass, "w", encoding="utf-8-sig") as f: f.write(header)
        return temp_ass
        
    try:
        with open(srt_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        blocks = re.split(r'\n\s*\n', content.strip())
        for b in blocks:
            lines = [x.strip() for x in b.split('\n') if x.strip()]
            if len(lines) >= 3:
                m = re.findall(r"(\d+:\d+:\d+[,.]\d+)", lines[1])
                if m:
                    s_s, e_s = str_to_sec(m[0]), str_to_sec(m[1])
                    text = " ".join(lines[2:])
                    
                    if preview_mode and s_s > 6.0:
                        continue
                        
                    s_t, e_t = sec_to_ass_time(s_s), sec_to_ass_time(e_s)
                    
                    chi = " ".join([t for t in text.split() if re.search(r'[\u4e00-\u9fff]', t)])
                    eng = " ".join([t for t in text.split() if not re.search(r'[\u4e00-\u9fff]', t)])
                    if not chi and text: chi = text
                    if chi: header += f"Dialogue: 0,{s_t},{e_t},ZH,,0,0,0,,{chi}\n"
                    if eng: header += f"Dialogue: 0,{s_t},{e_t},EN,,0,0,0,,{eng}\n"
    except Exception as e:
        print(f"ASS 錯誤: {e}")
        
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

    # 🔥 透過物理提取器拿到絕對乾淨的原始大檔路徑
    working_video_path = get_real_path(video)
    
    if isinstance(srt, str):
        srt_input_path = srt
    elif isinstance(srt, dict) and 'name' in srt:
        srt_input_path = srt['name']
    else:
        srt_input_path = getattr(srt, 'name', None)
            
    if not working_video_path or not os.path.exists(working_video_path):
        return None, "❌ 錯誤：硬碟中找不到實體原始影片，請重新整理網頁上傳。"
    
    is_preview = (mode == "preview")
    output_path = "preview_subtitled.mp4" if is_preview else "output_subtitled.mp4"
    
    # 清理舊輸出，避免檔案鎖定
    if os.path.exists(output_path):
        try: os.remove(output_path)
        except:
            if not is_preview:
                output_path = "output_subtitled_final.mp4"
                
    # 暴力強制抹除任何可能干擾的歷史暫存壓縮檔名
    if os.path.exists("temp_auto_compressed_480p.mp4"):
        try: os.remove("temp_auto_compressed_480p.mp4")
        except: pass
    
    safe_ass_path = os.path.abspath(create_ass_file(
        srt_input_path, 
        res_w, res_h, pad_height, pos_y, 
        font_zh, font_en, int(zh_size), int(en_size), 
        color_zh, color_en, zh_bold, zh_italic, en_bold, en_italic,
        preview_mode=is_preview
    ))
    
    # 限制雙線程，穩定壓製不撐爆 Railway 記憶體
    cmd = ["ffmpeg", "-y", "-threads", "2"]
    
    if is_preview:
        cmd += ["-ss", "00:00:00", "-t", "5", "-i", working_video_path]
    else:
        cmd += ["-i", working_video_path]
        
    cmd += ["-vf", f"scale={res_w}:{res_h},pad={res_w}:{res_h+pad_height}:0:0:black,subtitles='{safe_ass_path}'"]
           
    if is_preview:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-threads", "2", "-c:a", "aac", output_path]
    else:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-threads", "2", "-c:a", "aac", output_path]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        if is_preview:
            return output_path, "🔄 5 秒動態效果預覽生成成功！現在您可以反覆微調參數，或直接啟動全片轉檔任務。"
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
.video-container { height: 650px !important; }
.video-container video { height: 100% !important; object-fit: contain !important; }
.log-box textarea { background-color: #1a1a1a !important; color: #4af626 !important; font-family: monospace !important; font-size: 14px !important; }
#btn_preview { background: linear-gradient(135deg, #3498db, #2980b9) !important; color: white !important; font-weight: bold !important; }
#btn_run { background: linear-gradient(135deg, #27ae60, #219653) !important; color: white !important; font-weight: bold !important; }
.gr-group { border: 1px solid #bdc3c7 !important; border-radius: 8px !important; padding: 12px !important; background-color: #fcfcfc !important; }
"""

# 🔥【強迫重新編編識別碼】將 UI 版號正名為 V9.6-FINAL-FORCE，確保部署有確實生效
with gr.Blocks(title="Python Video Toolbox V9.6-FINAL-FORCE") as demo:
    gr.Markdown("# 🎬 Python Video Toolbox V9.6-FINAL-FORCE (徹底拔除舊暫存版)")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📁 【檔案選取與測試】")
            btn_test = gr.Button("🎯 一鍵載入測試檔案", variant="secondary")
            
            # 使用普通的通用檔案組件（非 gr.Video），徹底拆除 Gradio 長片自動預壓縮的隱藏地雷
            video_input = gr.File(label="1. 原始影片 (支援 .mp4, .mkv 大檔)", file_types=[".mp4", ".mkv"])
            srt_input = gr.File(label="2. 字幕檔案 (SRT)", file_types=[".srt"])
            
            gr.Markdown("### 📺 【解析度與黑框邊界】")
            resolution = gr.Dropdown(choices=["1920x1080", "1280x720", "854x480"], value="854x480", label="解析度")
            pad_height = gr.Slider(minimum=0, maximum=800, value=97, step=5, label="黑框高度 (px)")
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
            btn_preview = gr.Button("🔄 循環生成 5 秒動態預覽", variant="secondary", elem_id="btn_preview")
            btn_run = gr.Button("🚀 開始全片轉檔任務", variant="primary", elem_id="btn_run")
            
        with gr.Column(scale=1):
            gr.Markdown("### 🖥️ 【實時狀態與成果預覽】")
            log_output = gr.Textbox(label="狀態與實時日誌監控", placeholder="等待任務啟動...", lines=3, elem_classes="log-box")
            video_output = gr.Video(label="🚀 2. 轉檔成果 / 5秒預覽影片播放器", elem_classes="video-container")

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
    import os
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port, max_file_size="2gb", css=custom_css, show_api=False)
   )
