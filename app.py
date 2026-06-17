import os
import re
import glob
import subprocess
import shutil
import gradio as gr

# --- 測試檔案暫存路徑 ---
TEST_VIDEO = "test_video.mp4"
TEST_SRT = "test_subtitles.srt"

# ==========================================
# 【依賴檢查】
# ==========================================
def check_dependencies():
    """檢查必要的依賴和外部工具"""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("❌ FFmpeg 未安裝！請先安裝 FFmpeg：\n- Linux: sudo apt-get install ffmpeg\n- macOS: brew install ffmpeg\n- Windows: 從 https://ffmpeg.org/download.html 下載安裝")
    print("✅ FFmpeg 已就緒")

# ==========================================
# 【核心邏輯：時間與顏色轉換】
# ==========================================
def str_to_sec(s):
    """將 SRT 時間格式轉換為秒數"""
    try:
        s = s.replace(',', '.')
        h, m, sec = s.split(':')
        return int(h)*3600 + int(m)*60 + float(sec)
    except:
        return 0.0

def sec_to_ass_time(seconds):
    """將秒數轉換為 ASS 格式時間戳（h:mm:ss.cc）"""
    if seconds < 0: 
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:01d}:{m:02d}:{s:05.2f}"

def hex_to_ass_color(hex_str):
    """將 16 進制顏色代碼轉換為 ASS 格式顏色（BGR 反轉）"""
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
    """根據解析度自動調整字體大小和黑框高度"""
    try:
        current_h = int(res_text.split('x')[1])
        base_h = 1080
        ratio = current_h / base_h
        
        new_zh = max(10, int(100 * ratio))  # 確保最小字體大小
        new_en = max(10, int(50 * ratio))
        new_pad = max(0, int(220 * ratio))
        
        return new_zh, new_en, new_pad
    except:
        return 100, 50, 220

# ==========================================
# 【核心：上傳檔案真實路徑提取器】
# ==========================================
def get_real_path(video_obj):
    """從 Gradio 上傳物件中提取真實檔案路徑"""
    if not video_obj:
        return None
        
    path = None
    if isinstance(video_obj, str):
        path = video_obj
    elif isinstance(video_obj, dict) and 'name' in video_obj:
        path = video_obj['name']
    else:
        path = getattr(video_obj, 'name', None)
        
    # 如果路徑不存在或被標記為壓縮檔，搜索 /tmp 快取
    if not path or "temp_auto_compressed" in path or not os.path.exists(path):
        print("🕵️ 偵測到異常快取干擾，啟動全硬碟真實原檔肉搜...")
        found_files = glob.glob("/tmp/gradio/*/*.mp4") + glob.glob("/tmp/gradio/*/*.mkv")
        if found_files:
            # 挑出容量最大、不是壓縮版本的原始影片
            found_files.sort(key=lambda x: os.path.getsize(x), reverse=True)
            for f in found_files:
                if "temp_auto_compressed" not in f:
                    return f
    return path

# ==========================================
# 【核心：上傳檔案引導提示】
# ==========================================
def auto_pre_compress(video):
    """檢測上傳的影片並提供反饋"""
    real_path = get_real_path(video)
    if not real_path or not os.path.exists(real_path):
        return "❌ 錯誤：無法鎖定實體影片位置，請確認網頁上傳進度已達 100%。"
    
    file_size_mb = os.path.getsize(real_path) / (1024 * 1024)
    return f"⚡【系統提示】原始大影片已 100% 寫入雲端硬碟（大小: {file_size_mb:.1f} MB）！實體路徑已牢牢鎖定。現在您可以放心地反覆點擊「5秒預覽」或啟動完整轉檔！"

# ==========================================
# 【一鍵載入測試檔案】
# ==========================================
def load_test_files():
    """載入本地測試檔案"""
    v_path = TEST_VIDEO if os.path.exists(TEST_VIDEO) else None
    s_path = TEST_SRT if os.path.exists(TEST_SRT) else None
    
    msg = "【系統提示】已成功載入內建測試檔案！"
    if not v_path or not s_path:
        msg = "⚠️ 提示：空間內未偵測到 test_video.mp4 或 test_subtitles.srt。"
        
    return v_path, s_path, msg

# ==========================================
# 【讀取 SRT 檔案的多編碼方案】
# ==========================================
def read_srt_file(srt_path):
    """嘗試用多種編碼讀取 SRT 檔案"""
    encodings = ['utf-8-sig', 'utf-8', 'gbk', 'iso-8859-1', 'cp1252']
    
    for encoding in encodings:
        try:
            with open(srt_path, "r", encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    
    # 最後嘗試忽略錯誤的字符
    try:
        with open(srt_path, "r", encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ 警告：無法讀取 SRT 檔案: {e}")
        return None

# ==========================================
# 【中英文字幕分離】
# ==========================================
def separate_chinese_english(text):
    """
    分離中文和英文字幕
    - 中文：只提取中文字符
    - 英文：提取非中文字符（包括英文、數字、標點符號）
    """
    chi_chars = []
    eng_text = []
    
    for char in text:
        if re.search(r'[\u4e00-\u9fff]', char):
            # 中文字符
            chi_chars.append(char)
        else:
            # 非中文字符
            eng_text.append(char)
    
    chi = ''.join(chi_chars).strip()
    eng = ''.join(eng_text).strip()
    
    return chi, eng

# ==========================================
# 【生成 ASS 字幕檔】
# ==========================================
def create_ass_file(srt_path, res_w, res_h, pad_h, pos_y, font_zh, font_en, zh_size, en_size, color_zh, color_en, zh_bold, zh_italic, en_bold, en_italic, preview_mode=False):
    """生成 ASS 格式字幕檔"""
    temp_ass = "preview_render.ass" if preview_mode else "full_render.ass"
    ratio = res_h / 1080.0
    
    # 計算邊距
    m_v = int(pad_h / 2) + pos_y
    zh_margin = m_v + int(en_size) + int(15 * ratio)
    
    # 顏色轉換
    ass_c_zh = hex_to_ass_color(color_zh)
    ass_c_en = hex_to_ass_color(color_en)
    
    # 粗體和斜體標誌
    z_b = 1 if zh_bold else 0
    z_i = 1 if zh_italic else 0
    e_b = 1 if en_bold else 0
    e_i = 1 if en_italic else 0
    
    # ASS 檔案頭部
    header = f"[Script Info]\nPlayResX: {res_w}\nPlayResY: {res_h+pad_h}\nScaledBorderAndShadow: yes\n\n"
    header += "[v4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Bold, Italic, Alignment, MarginV, Outline, Shadow, BorderStyle\n"
    header += f"Style: ZH,{font_zh},{int(zh_size)},{ass_c_zh},{z_b},{z_i},2,{zh_margin},2,0,1\n"
    header += f"Style: EN,{font_en},{int(en_size)},{ass_c_en},{e_b},{e_i},2,{m_v},2,0,1\n\n"
    header += "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    
    # 如果沒有 SRT 檔案，只生成頭部
    if not srt_path:
        with open(temp_ass, "w", encoding="utf-8-sig") as f: 
            f.write(header)
        return temp_ass
    
    # 解析 SRT 檔案
    try:
        content = read_srt_file(srt_path)
        if not content:
            with open(temp_ass, "w", encoding="utf-8-sig") as f:
                f.write(header)
            return temp_ass
        
        blocks = re.split(r'\n\s*\n', content.strip())
        for b in blocks:
            lines = [x.strip() for x in b.split('\n') if x.strip()]
            if len(lines) >= 3:
                # 提取時間戳
                m = re.findall(r"(\d+:\d+:\d+[,.]\d+)", lines[1])
                if m and len(m) >= 2:
                    s_s = str_to_sec(m[0])
                    e_s = str_to_sec(m[1])
                    text = " ".join(lines[2:])
                    
                    # 預覽模式只顯示前 6 秒
                    if preview_mode and s_s > 6.0:
                        continue
                    
                    # 轉換時間格式
                    s_t = sec_to_ass_time(s_s)
                    e_t = sec_to_ass_time(e_s)
                    
                    # 分離中英文
                    chi, eng = separate_chinese_english(text)
                    
                    # 如果沒有中文但有文本，全部作為中文
                    if not chi and text:
                        chi = text
                    
                    # 寫入對話行
                    if chi:
                        header += f"Dialogue: 0,{s_t},{e_t},ZH,,0,0,0,,{chi}\n"
                    if eng:
                        header += f"Dialogue: 0,{s_t},{e_t},EN,,0,0,0,,{eng}\n"
                        
    except Exception as e:
        print(f"⚠️ ASS 生成警告: {e}")
        
    # 寫入最終 ASS 檔案
    with open(temp_ass, "w", encoding="utf-8-sig") as f:
        f.write(header)
    return temp_ass

# ==========================================
# 【核心：FFmpeg 轉檔/預覽處理中心】
# ==========================================
def process_video_task(video, srt, resolution, pad_height, pos_y, font_zh, font_en, zh_size, en_size, color_zh, color_en, zh_bold, zh_italic, en_bold, en_italic, mode="full"):
    """轉檔或預覽視頻"""
    if not video or not srt:
        return None, "❌ 錯誤：請先上傳影片與 SRT 字幕檔！"
    
    # 驗證輸入參數
    try:
        res_w, res_h = map(int, resolution.split('x'))
        pad_height = max(0, int(pad_height))
        zh_size = max(10, int(zh_size))
        en_size = max(10, int(en_size))
    except ValueError:
        return None, "❌ 錯誤：解析度或字體大小格式不正確！"

    # 取得原始大影片實體路徑
    working_video_path = get_real_path(video)
    
    if isinstance(srt, str):
        srt_input_path = srt
    elif isinstance(srt, dict) and 'name' in srt:
        srt_input_path = srt['name']
    else:
        srt_input_path = getattr(srt, 'name', None)
            
    if not working_video_path or not os.path.exists(working_video_path):
        return None, "❌ 錯誤：硬碟中找不到實體原始影片，請重新整理網頁上傳。"
    
    if not srt_input_path or not os.path.exists(srt_input_path):
        return None, "❌ 錯誤：無法找到 SRT 字幕檔案！"
    
    is_preview = (mode == "preview")
    output_path = "preview_subtitled.mp4" if is_preview else "output_subtitled.mp4"
    
    # 清理舊檔案
    if os.path.exists(output_path):
        try: 
            os.remove(output_path)
        except:
            if not is_preview:
                output_path = "output_subtitled_final.mp4"
                
    # 清理殘留的壓縮檔
    if os.path.exists("temp_auto_compressed_480p.mp4"):
        try: 
            os.remove("temp_auto_compressed_480p.mp4")
        except: 
            pass
    
    # 生成 ASS 字幕檔
    safe_ass_path = os.path.abspath(create_ass_file(
        srt_input_path, 
        res_w, res_h, pad_height, pos_y, 
        font_zh, font_en, zh_size, en_size, 
        color_zh, color_en, zh_bold, zh_italic, en_bold, en_italic,
        preview_mode=is_preview
    ))
    
    # 構建 FFmpeg 命令
    cmd = ["ffmpeg", "-y", "-threads", "2"]
    
    if is_preview:
        cmd += ["-ss", "00:00:00", "-t", "5", "-i", working_video_path]
    else:
        cmd += ["-i", working_video_path]
        
    # 使用絕對路徑，避免引號問題
    cmd += ["-vf", f"scale={res_w}:{res_h},pad={res_w}:{res_h+pad_height}:0:0:black,subtitles={safe_ass_path}"]
           
    if is_preview:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-threads", "2", "-c:a", "aac", output_path]
    else:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-threads", "2", "-c:a", "aac", output_path]
    
    # 執行 FFmpeg
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return None, "❌ 轉檔超時（超過 1 小時）"
    except Exception as e:
        return None, f"❌ 執行 FFmpeg 時發生錯誤: {str(e)}"
    
    if result.returncode == 0:
        if is_preview:
            return output_path, "🔄 5 秒動態效果預覽生成成功！現在您可以反覆微調參數，或直接啟動全片轉檔。"
        else:
            return output_path, "✨ 全片轉檔成功！"
    else:
        error_msg = result.stderr if result.stderr else "未知錯誤"
        return None, f"❌ 轉檔發生異常中止。\n錯誤日誌：\n{error_msg}"

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

# ==========================================
# 【Gradio UI 介面】
# ==========================================
with gr.Blocks(title="Python Video Toolbox V9.6") as demo:
    gr.Markdown("# 🎬 Python Video Toolbox V9.6 - Railway 雲端獨立版")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📁 【檔案選取與測試】")
            btn_test = gr.Button("🎯 一鍵載入測試檔案", variant="secondary")
            
            # 使用普通的通用檔案組件
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
                    zh_size = gr.Number(value=44, label="字體大小", minimum=10, maximum=200)
                    color_zh = gr.ColorPicker(value="#FFFFFF", label="字體顏色")

            with gr.Group(elem_classes="gr-group"):
                gr.Markdown("#### 🔤 【英文字體樣式】")
                font_en = gr.Dropdown(choices=["Arial", "Times New Roman"], value="Arial", label="英文字型")
                with gr.Row():
                    en_bold = gr.Checkbox(label="粗體", value=False)
                    en_italic = gr.Checkbox(label="斜體", value=True)
                with gr.Row():
                    en_size = gr.Number(value=22, label="字體大小", minimum=10, maximum=200)
                    color_en = gr.ColorPicker(value="#FFFF00", label="字體顏色")
                    
            gr.Markdown("### 🚀 【功能執行】")
            btn_preview = gr.Button("🔄 循環生成 5 秒動態預覽", variant="secondary", elem_id="btn_preview")
            btn_run = gr.Button("🚀 開始全片轉檔任務", variant="primary", elem_id="btn_run")
            
        with gr.Column(scale=1):
            gr.Markdown("### 🖥️ 【實時狀態與成果預覽】")
            log_output = gr.Textbox(label="狀態與實時日誌監控", placeholder="等待任務啟動...", lines=3, elem_classes="log-box")
            video_output = gr.Video(label="🚀 2. 轉檔成果 / 5秒預覽影片播放器", elem_classes="video-container")

    # 事件綁定
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
    check_dependencies()
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port, max_file_size="2gb", css=custom_css, show_api=False)
