import os
import subprocess
import uuid
import re
import shutil
import time
import threading
import gradio as gr

# =========================================================
# 基本設定
# =========================================================
TEMP_DIR = "temp_files"
os.makedirs(TEMP_DIR, exist_ok=True)

TEMP_FILE_EXPIRE_HOURS = 6
PREVIEW_SECONDS = 120


# =========================================================
# 工具函式：背景清理舊暫存檔
# =========================================================
def cleanup_old_temp_files(folder=TEMP_DIR, expire_hours=TEMP_FILE_EXPIRE_HOURS):
    if not os.path.exists(folder):
        return
    now = time.time()
    expire_seconds = expire_hours * 3600
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            try:
                mtime = os.path.getmtime(path)
                if now - mtime > expire_seconds:
                    os.remove(path)
                    print(f"[清理] 已刪除舊暫存檔: {path}")
            except Exception as e:
                print(f"[清理警告] 刪除檔案失敗 {path}: {e}")
    except Exception as e:
        print(f"[清理警告] 掃描暫存資料夾失敗: {e}")


def start_background_cleanup():
    def loop():
        while True:
            cleanup_old_temp_files()
            time.sleep(3600)
    cleanup_old_temp_files()
    t = threading.Thread(target=loop, daemon=True)
    t.start()


# =========================================================
# 工具函式：確認 ffmpeg / ffprobe 是否存在
# =========================================================
def check_ffmpeg_tools():
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if not ffmpeg_path:
        print("【系統警告】找不到 ffmpeg，請確認 Railway 已安裝 ffmpeg。")
    else:
        print(f"【系統初始化】ffmpeg 路徑: {ffmpeg_path}")
    if not ffprobe_path:
        print("【系統警告】找不到 ffprobe，請確認 Railway 已安裝 ffmpeg。")
    else:
        print(f"【系統初始化】ffprobe 路徑: {ffprobe_path}")


# =========================================================
# 影片解析度偵測
# =========================================================
def get_video_height(video_path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=height",
        "-of", "csv=s=x:p=0",
        video_path
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        height = int(result.stdout.strip())
        return height
    except Exception as e:
        print(f"偵測影片解析度失敗，保底設定為 1080。錯誤: {e}")
        return 1080


# =========================================================
# 字幕清理與雙語字體/顏色分離（安全優化版 .srt）
# =========================================================
def clean_and_prepare_srt(input_sub_path, output_sub_path):
    try:
        with open(input_sub_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        # 統一換行符號為 \n，並依據空行切分成一個個字幕區塊
        blocks = content.replace("\r\n", "\n").split("\n\n")
        processed_blocks = []
        
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 3:
                if block.strip():
                    processed_blocks.append(block.strip())
                continue
                
            seq = lines[0]
            timeline = lines[1]
            sub_text_lines = lines[2:]  # 實際的字幕文字行
            
            new_sub_lines = []
            for i, text_line in enumerate(sub_text_lines):
                # 移除任何原本殘留的標籤，確保乾淨
                cleaned_line = re.sub(r"<[^>]+>", "", text_line)
                cleaned_line = re.sub(r"\{[^}]+\}", "", cleaned_line).strip()
                
                if not cleaned_line:
                    continue
                
                # 安全結構判斷：如果總共有多行字幕，且目前讀到第二行（通常就是英文/外文行）
                if len(sub_text_lines) >= 2 and i == 1:
                    # 💡 這裡同時設定了 size="-2"（縮小）與 color="#FFFF00"（變黃色）
                    new_sub_lines.append(f'<font size="-2" color="#FFFF00">{cleaned_line}</font>')
                else:
                    new_sub_lines.append(cleaned_line)
            
            # 重新拼回單個字幕區塊
            new_block = f"{seq}\n{timeline}\n" + "\n".join(new_sub_lines)
            processed_blocks.append(new_block)
            
        # 將所有區塊拼回完整的 srt 檔案
        with open(output_sub_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(processed_blocks) + "\n\n")
        return True
    except Exception as e:
        print(f"字幕純淨化與雙語分離失敗: {e}")
        return False


# =========================================================
# 產生字幕濾鏡（含強制樣式）
# =========================================================
def build_subtitle_filter(subtitle_path, font_size, margin_v):
    safe_sub_path = subtitle_path.replace("\\", "/").replace(":", "\\:")
    style = (
        f"Fontname=Noto Sans CJK TC,"
        f"FontSize={font_size},"
        f"BorderStyle=1,"
        f"Outline=1.0,"
        f"Shadow=0,"
        f"MarginV={margin_v}"
    )
    return f"subtitles='{safe_sub_path}':force_style='{style}'"


# =========================================================
# 核心：影片與字幕合併
# =========================================================
def merge_video_subtitle(video_path, subtitle_path, cn_size, target_resolution, force_ass_style, preview_mode=False):
    if not video_path or not subtitle_path:
        return None, "❌ 請確認已上傳影片與字幕檔案。"

    cleanup_old_temp_files()
    task_id = str(uuid.uuid4())

    sub_ext = os.path.splitext(subtitle_path)[1].lower()
    final_sub_path = subtitle_path
    
    # 判斷是否需要強制套用樣式
    use_force_style = False
    if sub_ext == ".srt":
        cleaned_sub_path = os.path.join(TEMP_DIR, f"clean_{task_id}.srt")
        if clean_and_prepare_srt(subtitle_path, cleaned_sub_path):
            final_sub_path = cleaned_sub_path
        use_force_style = True
    elif sub_ext in [".ass", ".ssa", ".ast"]:
        final_sub_path = subtitle_path
        use_force_style = force_ass_style
    else:
        cleaned_sub_path = os.path.join(TEMP_DIR, f"clean_{task_id}.srt")
        if clean_and_prepare_srt(subtitle_path, cleaned_sub_path):
            final_sub_path = cleaned_sub_path
        use_force_style = True

    prefix = "preview_" if preview_mode else "full_"
    output_path = os.path.join(TEMP_DIR, f"{prefix}{task_id}.mp4")

    # ========== 解析度與縮放比例計算 ==========
    orig_height = get_video_height(video_path)
    
    if target_resolution == "1080p (1920x1080)":
        target_height = 1080
    elif target_resolution == "720p (1280x720)":
        target_height = 720
    elif target_resolution == "480p (854x480)":
        target_height = 480
    else:
        target_height = orig_height  # 原始解析度

    # 根據「最終輸出的解析度」來計算字體縮放比例
    scale_factor = target_height / 1080.0
    final_cn_size = max(int(cn_size * scale_factor), 15)
    final_margin_v = max(int(15 * scale_factor), 6)

    # 構建 FFmpeg 濾鏡鏈 (先縮放解析度，再壓字幕)
    filter_elements = []
    if target_height != orig_height:
        filter_elements.append(f"scale=-2:{target_height}")

    if use_force_style:
        sub_filter = build_subtitle_filter(
            subtitle_path=final_sub_path,
            font_size=final_cn_size,
            margin_v=final_margin_v
        )
    else:
        safe_sub_path = final_sub_path.replace("\\", "/").replace(":", "\\:")
        sub_filter = f"subtitles='{safe_sub_path}'"
    
    filter_elements.append(sub_filter)
    video_filter = ",".join(filter_elements)

    mode_text = "【測試模式 - 僅擷取前2分鐘】" if preview_mode else "【正式完整模式】"
    info_msg = (
        f"{mode_text}\n"
        f"原始高度: {orig_height}px -> 輸出高度: {target_height}px。\n"
        f"字幕類型: {sub_ext}\n"
        f"字體樣式: {'❌ 使用字幕原生樣式' if not use_force_style else f'⚠️ 強制覆蓋樣式 (主行: {final_cn_size}px 白色，次行: 自動縮小且變黃色)'}"
    )

    cmd = ["ffmpeg", "-y", "-i", video_path]
    if preview_mode:
        cmd.extend(["-t", str(PREVIEW_SECONDS)])
    cmd.extend([
        "-vf", video_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "copy",
        output_path
    ])

    print("\n========== FFmpeg 執行開始 ==========")
    print("FFmpeg 命令：")
    print(" ".join(cmd))
    print("====================================\n")

    try:
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        if process.returncode != 0:
            print("FFmpeg 錯誤日誌：\n", process.stderr)
            return None, f"❌ FFmpeg 壓製失敗。\n\n{process.stderr}"

        if use_force_style and final_sub_path != subtitle_path:
            try:
                os.remove(final_sub_path)
            except Exception:
                pass

        if not os.path.exists(output_path):
            return None, "❌ FFmpeg 看似成功，但找不到輸出檔案。"

        return (
            output_path,
            f"✨ 影片與字幕合併成功！\n\n【系統通知】\n{info_msg}\n檔案已就緒，可於右側直接播放或下載。"
        )
    except Exception as e:
        return None, f"❌ 伺服器內部發生錯誤：{str(e)}"


# =========================================================
# Gradio 按鈕分流函式
# =========================================================
def handle_full_merge(video, subtitle, cn_sz, res, force_ass):
    return merge_video_subtitle(video, subtitle, cn_sz, res, force_ass, preview_mode=False)

def handle_preview_merge(video, subtitle, cn_sz, res, force_ass):
    return merge_video_subtitle(video, subtitle, cn_sz, res, force_ass, preview_mode=True)


# =========================================================
# 啟動初始化
# =========================================================
check_ffmpeg_tools()
start_background_cleanup()


# =========================================================
# Gradio UI
# =========================================================
with gr.Blocks(theme=gr.themes.Soft(primary_hue=gr.themes.colors.indigo)) as demo:
    gr.Markdown("# 🎬 影片與字幕自動合併工具 (電影級雙語字體版)")

    with gr.Row():
        with gr.Column():
            video_input = gr.Video(
                label="1. 上傳原始影片 (MP4 / MKV)",
                height=360
            )

            sub_input = gr.File(
                label="2. 上傳字幕檔案 (.srt / .ass / .ssa / .ast)",
                file_types=[".srt", ".ass", ".ssa", ".ast"]
            )

            with gr.Row():
                # 解析度選擇器
                resolution_input = gr.Dropdown(
                    choices=["原始解析度", "1080p (1920x1080)", "720p (1280x720)", "480p (854x480)"],
                    value="1080p (1920x1080)",
                    label="3. 輸出影片解析度",
                    info="調整解析度可直接影響字幕的相對大小，並加快壓製速度"
                )
                
                # 是否強制覆蓋 ASS 樣式
                force_ass_style_input = gr.Checkbox(
                    label="強制修改 ASS/AST 字幕大小",
                    value=True,
                    info="若打勾，滑桿設定將對 ASS 生效；若取消，則保留 ASS 原生特效與字體大小。"
                )

            with gr.Row():
                cn_size_input = gr.Slider(
                    minimum=10,
                    maximum=100,         
                    value=45,            
                    step=1,
                    label="主要中文字幕大小 (白色)",
                    info="建議：1080p 設 45~55，720p 設 30~40（雙語 .srt 字幕中的第二行會自動縮小並變黃色）"
                )

            with gr.Row():
                btn_preview = gr.Button("⏱️ 測試合併（僅前2分鐘）", variant="secondary")
                btn_submit = gr.Button("🚀 開始正式完整合併", variant="primary")

        with gr.Column():
            video_output = gr.Video(
                label="4. 合併結果影片",
                height=360
            )

            status_output = gr.Textbox(
                label="執行狀態 / 錯誤日誌",
                interactive=False,
                placeholder="等待操作中..."
            )

    btn_preview.click(
        fn=handle_preview_merge,
        inputs=[video_input, sub_input, cn_size_input, resolution_input, force_ass_style_input],
        outputs=[video_output, status_output]
    )

    btn_submit.click(
        fn=handle_full_merge,
        inputs=[video_input, sub_input, cn_size_input, resolution_input, force_ass_style_input],
        outputs=[video_output, status_output]
    )


# =========================================================
# Railway 啟動
# =========================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(
        server_name="0.0.0.0",
        server_port=port,
        show_error=True
    )
