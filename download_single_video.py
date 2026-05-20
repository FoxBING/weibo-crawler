#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import json
import json5
import re
import warnings
warnings.filterwarnings("ignore")

def get_script_path():
    return os.path.dirname(os.path.realpath(__file__))

def download_video(session, headers, weibo_id, output_dir):
    """下载单个微博的视频"""
    url = f"https://m.weibo.cn/detail/{weibo_id}"
    print(f"\n获取微博 {weibo_id} 的详情...")

    try:
        html = session.get(url, headers=headers, verify=False).text

        # 解析 JSON
        html = html[html.find('"status":') :]
        html = html[: html.rfind('"call"')]
        html = html[: html.rfind(",")]
        html = "{" + html + "}"
        data = json.loads(html, strict=False)

        # 数据在 data["status"] 中
        weibo_info = data.get("status", {})
        
        if not weibo_info:
            print(f"  错误: 没有获取到微博信息")
            return False

        text = weibo_info.get("text", "")
        if text:
            text = re.sub(r'<[^>]+>', '', text)
        print(f"  微博内容: {text[:80]}...")

        # 获取视频 URL - 从多个来源获取
        video_urls = []

        # 1. 从 pics 中提取多视频（type=video）
        if weibo_info.get("pics"):
            for pic in weibo_info["pics"]:
                if isinstance(pic, dict) and pic.get("type") == "video" and pic.get("videoSrc"):
                    video_urls.append(pic["videoSrc"])
                    print(f"  从 pics 中找到视频: {pic['videoSrc'][:60]}...")

        # 2. 从 page_info 中获取
        page_info = weibo_info.get("page_info", {})
        
        # 优先使用 media_info 或 urls 中的直接下载地址
        if not video_urls:
            media_info = page_info.get("media_info") or page_info.get("urls") or {}
            if media_info:
                direct_url = (media_info.get("mp4_720p_mp4") or
                             media_info.get("mp4_hd_mp4") or
                             media_info.get("mp4_hd_url") or
                             media_info.get("hevc_mp4_hd") or
                             media_info.get("mp4_sd_url") or
                             media_info.get("mp4_ld_mp4") or
                             media_info.get("stream_url_hd") or
                             media_info.get("stream_url"))
                if direct_url:
                    video_urls.append(direct_url)
                    print(f"  找到直接下载地址: {direct_url[:60]}...")

        # 回退到 video.weibo.com/show 格式
        if not video_urls:
            page_url = page_info.get("page_url", "")
            if page_url and "fid=" in page_url:
                match = re.search(r'fid=([^&]*)', page_url)
                if match:
                    from urllib.parse import unquote
                    video_urls.append(f"https://video.weibo.com/show?fid={unquote(match.group(1))}")
                    print(f"  找到 video.weibo.com URL")

        if not video_urls:
            print(f"  没有找到视频")
            return False

        # 下载视频
        success = False
        for i, url in enumerate(video_urls):
            if url.startswith("https://video.weibo.com/show"):
                print(f"  [{i+1}] 使用 yt-dlp 下载...")
                file_path = os.path.join(
                    output_dir, "video", "原创微博视频",
                    f"{weibo_id}_{i+1}.%(ext)s"
                )
                os.makedirs(os.path.dirname(file_path), exist_ok=True)

                cmd = f'yt-dlp "{url}" --output "{file_path}"'
                import subprocess
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"    ✓ yt-dlp 下载成功")
                    success = True
                else:
                    print(f"    ✗ yt-dlp 失败")
            else:
                print(f"  [{i+1}] 直接下载...")
                file_path = os.path.join(
                    output_dir, "video", "原创微博视频",
                    f"{weibo_id}_{i+1}.mp4"
                )
                os.makedirs(os.path.dirname(file_path), exist_ok=True)

                try:
                    response = session.get(url, headers=headers, verify=False, timeout=(10, 60), stream=True)
                    response.raise_for_status()

                    total_size = int(response.headers.get('Content-Length', 0))
                    downloaded = 0

                    with open(file_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=1024 * 64):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size:
                                    percent = downloaded * 100 / total_size
                                    print(f"\r    下载进度: {percent:.1f}%", end="", flush=True)

                    print(f"\n    ✓ 已保存到: {file_path}")
                    success = True
                except Exception as e:
                    print(f"\n    ✗ 下载失败: {e}")

        return success

    except Exception as e:
        print(f"  错误: {e}")
        return False

def process_failed_file(session, headers, failed_file, user_folder):
    """处理单个 failed_yt-dlp_commands.txt 文件"""
    output_dir = os.path.join(get_script_path(), "weibo_data", user_folder)
    
    with open(failed_file, "r", encoding="utf-8") as f:
        commands = f.readlines()

    # 提取唯一的微博 ID
    weibo_ids = set()
    for cmd in commands:
        cmd = cmd.strip()
        if not cmd:
            continue
        
        # 从输出路径中提取微博 ID
        match = re.search(r'(\d{8}T_(\d+))', cmd)
        if match:
            weibo_ids.add(match.group(2))

    weibo_ids = sorted(weibo_ids, reverse=True)
    print(f"\n=== {user_folder}: {len(weibo_ids)} 个微博 ID ===")

    success_count = 0
    fail_count = 0

    for i, weibo_id in enumerate(weibo_ids, 1):
        print(f"\n[{i}/{len(weibo_ids)}] 处理微博 {weibo_id}...")
        
        if download_video(session, headers, weibo_id, output_dir):
            success_count += 1
        else:
            fail_count += 1

    print(f"\n完成: 成功 {success_count}, 失败 {fail_count}")
    return success_count, fail_count

def main():
    import requests

    # 从 config.json 读取 Cookie
    config_path = os.path.join(get_script_path(), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json5.load(f)

    cookie_string = config.get("cookie", "")
    if not cookie_string:
        print("错误: config.json 中没有配置 cookie")
        return

    # 解析 Cookie
    cookies = {}
    for pair in cookie_string.split(';'):
        if '=' in pair:
            key, value = pair.split('=', 1)
            cookies[key.strip()] = value.strip()

    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
        'Referer': 'https://m.weibo.cn/',
        'Accept': 'application/json, text/plain, */*',
    }

    # 创建 session
    session = requests.Session()
    session.cookies.update(cookies)

    # 预热 session
    print("预热 session...")
    session.get("https://m.weibo.cn", headers=headers, timeout=10)
    print("Session 预热完成")

    # 遍历 weibo_data 目录
    weibo_data_dir = os.path.join(get_script_path(), "weibo_data")
    
    if not os.path.exists(weibo_data_dir):
        print(f"目录不存在: {weibo_data_dir}")
        return

    # 找到所有 failed_yt-dlp_commands.txt
    failed_files = []
    for item in os.listdir(weibo_data_dir):
        item_path = os.path.join(weibo_data_dir, item)
        if os.path.isdir(item_path):
            failed_file = os.path.join(item_path, "video", "failed_yt-dlp_commands.txt")
            if os.path.exists(failed_file):
                failed_files.append((failed_file, item))
                print(f"找到: {item}/video/failed_yt-dlp_commands.txt")

    if not failed_files:
        print("没有找到任何 failed_yt-dlp_commands.txt")
        return

    print(f"\n共找到 {len(failed_files)} 个文件")
    print("=" * 50)

    total_success = 0
    total_fail = 0

    for failed_file, user_folder in failed_files:
        print(f"\n{'='*50}")
        print(f"处理: {user_folder}")
        print("=" * 50)
        
        s, f = process_failed_file(session, headers, failed_file, user_folder)
        total_success += s
        total_fail += f

    print("\n" + "=" * 50)
    print(f"全部完成: 成功 {total_success}, 失败 {total_fail}")

if __name__ == "__main__":
    main()
