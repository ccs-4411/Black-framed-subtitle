import os
import sys
import subprocess
import shutil
import re
import gradio as gr

# =====================================================================
# 🛠️ 環境修復：自動偵測並強制修復 FFmpeg 在 Railway 上的環境路徑
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
# 📝 字幕處理：SRT 轉成帶有黑邊優化樣式的 ASS 字幕格式
# =====================================================================
def srt_to_ass(srt_path, ass_path):
    """將 SRT 字幕轉換為帶有客製化中英雙語樣式的 ASS 字幕檔案"""
    if not os.path.exists(srt_path):
        return False
        
    ass_header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 854\n"
        "PlayResY: 480\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # 預設雙語樣式：白字、無邊框、無陰影、置中
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,2,10,10,15,1\n\n"
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
            text_lines = lines[2:]
            
            match = re.match(r'(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)', time_line)
            if match:
                g = match.groups()
                start_ass = f"{int(g[0])}:{g[1]}:{g[2]}.{int(g[3])//10:02d}"
                end_ass = f"{int(g[4])}:{g[5]}:{g[6]}.{int(g[7])//10:02d}"
                
                full_text = "\\N".join(text_lines)
                full_text = re.sub(r'<[^>]+>', '', full_text)
                
                ass_lines.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{full_text}")
                
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        f.write("\n".join(ass_lines))
    return True

# =====================================================================
# 🎬 影音控制：呼叫 FFmpeg 進行影片處理與字幕燒錄
# =====================================================================
def process_video_task(video_input, subtitle_input, progress=gr.Progress()):
    """處理預覽與全片轉檔的核心工作函數"""
    if not video_input or not subtitle_input:
        return None, "❌ 請先上傳影片檔案與字幕檔案！"
        
    progress(0, desc="🚀 正在準備影音處理環境...")
    
    # 獲取當前專案目錄的絕對路徑，確保檔案生成在絕對安全的位置
    current_dir = os.path.abspath(os.path.dirname(__file__))
    output_video = os.path.join(current_dir, "preview_subtitled.mp4")
    preview_ass = os.path.join(current_dir, "preview_render.ass")
    
    # 清理舊檔案
    if os.path.exists(output_video):
        os.remove(output_video)
    if os.path.exists(preview_ass):
        os.remove(preview_ass)
        
    # 1. 轉換字幕為 ASS
    progress(0.2, desc="📝 正在將 SRT 字幕編譯為雙語 ASS 格式...")
    if not srt_to_ass(subtitle_input, preview_ass):
        return None, "❌ 字幕格式轉換失敗，請檢查 SRT 檔案編碼是否為 UTF-8。"
        
    # 🛠️ 【核心 Debug 檢查】：確保實體檔案真的躺在硬碟裡
    if not os.path.exists(preview_ass) or os.path.getsize(preview_ass) == 0:
        return None, f"❌ 實體 ASS 檔案未成功寫入磁碟！路徑: {preview_ass}"
    
    # 🛠️ 【關鍵修正】：對 Linux FFmpeg 的 subtitles 濾鏡進行雙重特殊字元轉義
    # 針對 Linux：冒號變 \: ，斜線變 \/，最後外面包裹單引號
    escaped_ass_path = preview_ass.replace(":", "\\:").replace("/", "\\/")
    subtitles_filter = f"subtitles='{escaped_ass_path}'"
    
    # 2. 建立 FFmpeg 轉檔指令
    cmd = [
        FFMPEG_PATH, "-y",
        "-threads", "2",
        "-ss", "00:00:00",
        "-t", "10",
        "-i", video_input,
        "-vf", f"scale=854:480,pad=854:575:0:0:black,{subtitles_filter}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-c:a", "aac",
        output_video
    ]
    
    log_msg = f"🎬 執行指令: {' '.join(cmd)}\n\n⏳ 正在調用 FFmpeg 轉碼中...\n"
    print(log_msg)
    progress(0.5, desc="🎬 FFmpeg 背景轉碼渲染中（10秒預覽）...")
    
    # 3. 執行指令並安全捕獲錯誤
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(result.stdout)
        
        if os.path.exists(output_video) and os.path.getsize(output_video) > 0:
            progress(1.0, desc="✅ 預覽轉檔成功！")
            return output_video, log_msg + "\n🎉 10秒影片預覽渲染完成！請在右側播放器檢視成果。"
        else:
            return None, log_msg + f"\n❌ 轉檔失敗，未能生成輸出檔案。\n環境錯誤資訊:\n{result.stderr}"
            
    except subprocess.CalledProcessError as e:
        error_msg = log_msg + f"\n💥 FFmpeg 執行失敗 (傳回碼 {e.returncode})。\n\n【FFmpeg stderr】\n{e.stderr}"
        print(error_msg)
        return None, error_msg
    except Exception as e:
        error_msg = log_msg + f"\n💥 系統發生未知錯誤: {str(e)}"
        print(error_msg)
        return None, error_msg

# =====================================================================
# 🎨 介面佈局：Gradio 6.0 現代美化 UI 組件
# =====================================================================
with gr.Blocks(theme=gr.themes.Soft(primary_hue="teal", secondary_hue="slate")) as demo:
    gr.Markdown(
        """
        # 🎬 Python Video Toolbox v9.8 (Railway Cloud)
        ### 雙語智能字幕渲染與黑框剪輯工具
        """
    )
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📂 1. 上傳來源檔案")
            video_file = gr.File(label="選擇原始影片 (MP4)", file_types=[".mp4"])
            subtitle_file = gr.File(label="選擇字幕檔案 (SRT)", file_types=[".srt"])
            
            gr.Markdown("### ⚙️ 2. 自動化工作流程")
            btn_preview = gr.Button("🔄 循環生成 10 秒動態預覽", variant="primary", size="lg")
            
        with gr.Column(scale=1):
            gr.Markdown("### 📺 3. 渲染成果預覽")
            video_output = gr.Video(label="雙語字幕加黑邊預覽播放器", interactive=False)
            
            gr.Markdown("### 📝 實時轉碼日誌與除錯監控")
            log_output = gr.Textbox(
                label="Console System Log", 
                placeholder="等待使用者觸發任務...", 
                lines=10,
                max_lines=15,
                autoscroll=True
            )

    btn_preview.click(
        fn=process_video_task,
        inputs=[video_file, subtitle_file],
        outputs=[video_output, log_output]
    )

# =====================================================================
# 🚀 啟動進入點
# =====================================================================
if __name__ == "__main__":
    server_port = int(os.environ.get("PORT", 7860))
    print(f"🚀 正在啟動生產環境網頁伺服器，監聽通訊埠: {server_port}")
    
   demo.launch(
        server_name="0.0.0.0",
        server_port=server_port
    )
