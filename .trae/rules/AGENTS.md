---
alwaysApply: false
description: 
---
# weibo-crawler 项目架构与逻辑文档

## 项目概述

微博爬虫，基于 `m.weibo.cn` 移动端 API，支持爬取用户微博、图片、视频、Live Photo、评论、转发，并以多种格式（Markdown/CSV/JSON/SQLite/MySQL/MongoDB）持久化。

---

## 目录结构

```
weibo-crawler/
├── weibo.py                  # 核心爬虫类 Weibo
├── config.json               # 运行配置（JSON5 格式，支持注释）
├── const.py                  # 全局常量（运行模式、Cookie 检查、通知）
├── __main__.py               # 入口
├── rename_files.py           # 批量重命名工具（独立脚本）
├── test_weibo.py             # 单条微博测试脚本
├── download_single_video.py  # 单视频下载工具
├── service.py                # 服务化封装
├── logging.conf              # 日志配置
├── util/
│   ├── csvutil.py            # CSV 读写工具（含增量更新逻辑）
│   ├── dateutil.py           # 日期工具
│   ├── notify.py             # PushDeer 通知
│   └── llm_analyzer.py       # LLM 内容分析器
├── weibo_data/               # 默认输出目录
│   └── <用户昵称或ID>/
│       ├── YYYY.md           # Markdown 微博存档
│       ├── img/              # 图片
│       ├── video/            # 视频
│       ├── live_photo/       # Live Photo 视频
│       └── <用户ID>.csv/json # 结构化数据
└── cookie.txt                # Cookie 文件（可选）
```

---

## 核心类 Weibo — 初始化与配置

### 配置项一览

| 配置键 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `user_id_list` | list/str | 必填 | 用户 ID 数组或指向 txt 文件的路径 |
| `only_crawl_original` | 0/1 | 0 | 1=仅原创，0=原创+转发 |
| `since_date` | str/int | 必填 | 起始时间，支持 `YYYY-MM-DD`、`YYYY-MM-DDTHH:MM:SS`、整数（天数） |
| `end_date` | str/int/"" | "" | 截止时间，为空不限制 |
| `start_page` | int | 1 | 断点续传起始页 |
| `page_weibo_count` | int | 10 | 每页微博数 |
| `write_mode` | list | 必填 | 输出格式：csv/json/mysql/mongo/sqlite/post/markdown |
| `markdown_split_by` | str | "day" | day/day_by_month/month/year/all |
| `original_pic_download` | 0/1 | 0 | 下载原创图片 |
| `retweet_pic_download` | 0/1 | 0 | 下载转发图片 |
| `original_video_download` | 0/1 | 0 | 下载原创视频 |
| `retweet_video_download` | 0/1 | 0 | 下载转发视频 |
| `original_live_photo_download` | 0/1 | 0 | 下载原创 Live Photo |
| `retweet_live_photo_download` | 0/1 | 0 | 下载转发 Live Photo |
| `download_comment` | 0/1 | 0 | 下载评论 |
| `comment_max_download_count` | int | 必填 | 单条微博最大评论数 |
| `comment_pic_download` | 0/1 | 0 | 下载评论图片 |
| `download_repost` | 0/1 | 0 | 下载转发 |
| `repost_max_download_count` | int | 必填 | 单条微博最大转发数 |
| `output_directory` | str | "weibo" | 输出根目录 |
| `user_id_as_folder_name` | 0/1 | 0 | 1=用用户 ID 作文件夹名，0=用昵称 |
| `remove_html_tag` | 0/1 | 0 | 移除微博正文 HTML 标签 |
| `cookie` | str | — | Cookie 字符串或 .txt 文件路径 |
| `write_time_in_exif` | 0/1 | 0 | 将发布时间写入 JPG EXIF |
| `change_file_time` | 0/1 | 0 | 修改文件系统时间 |
| `sqlite_db_path` | str | "weibodata.db" | SQLite 路径 |
| `store_binary_in_sqlite` | 0/1 | 0 | SQLite 中存储二进制 |
| `anti_ban_config` | object | {} | 防封禁配置（见下文） |
| `llm_config` | object | — | LLM 分析器配置 |

### Cookie 处理流程

```
1. 优先级：环境变量 WEIBO_COOKIE > config.json 中的 cookie 字段
2. 如果 cookie 值以 .txt 结尾 → 从文件读取
3. Cookie 清洗：
   - 提取核心 SUB 字段 → core_cookies
   - 提取备份 _T_WM / XSRF-TOKEN → backup_cookies
   - 若无 SUB → 全量加载
4. Session 预热：GET https://m.weibo.cn（仅带 SUB）
   - 成功 → 服务器下发新指纹
   - 失败 → 回退使用 backup_cookies
5. 程序结束时 → save_cookies_to_file() 写回文件
```

### 防封禁机制 (anti_ban_config)

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | false | 总开关 |
| `max_weibo_per_session` | 500 | 单次最大微博数 |
| `batch_size` | 50 | 批次大小 |
| `batch_delay` | 30 | 批次间延迟（秒） |
| `request_delay_min` | 8 | 请求最小延迟 |
| `request_delay_max` | 15 | 请求最大延迟 |
| `max_session_time` | 600 | 最大运行时间（秒） |
| `max_api_errors` | 5 | 最大 API 错误数 |
| `rest_time_min` | 180 | 休息时长（秒） |
| `random_rest_probability` | 0 | 随机休息概率 |
| `user_agents` | [...] | UA 池 |
| `accept_languages` | [...] | 语言池 |
| `referer_list` | [...] | Referer 池 |

**动态延迟算法**：
- 基础延迟 = `request_delay_min`
- 请求 > 100 次 → +5s；> 300 次 → +10s
- 运行 > 5 分钟 → +5s
- 最终延迟 = `uniform(base, request_delay_max)`

**暂停条件**：达到微博数上限 / 运行时间过长 / API 错误过多 / 随机触发

---

## 核心爬取流程

### 主流程 (`start → get_pages`)

```
start()
  └─ 遍历 user_config_list
       ├─ initialize_info()          # 重置 weibo/user/got_count/weibo_id_list
       ├─ get_pages()
       │    ├─ get_user_info()       # 获取用户信息 → user_to_database()
       │    ├─ 循环翻页 get_one_page(page)
       │    │    ├─ get_weibo_json(page)     # 请求 API
       │    │    └─ 遍历 cards → get_one_weibo(w)
       │    │         ├─ 长微博 → get_long_weibo(id)
       │    │         ├─ parse_weibo(weibo_info)  # 解析微博
       │    │         └─ 日期/去重过滤 → 加入 self.weibo
       │    ├─ 每 10 页 → write_data()
       │    └─ 最终 → write_data()
       ├─ export_comments_to_csv_for_current_user()
       ├─ execute_stored_video_downloads()   # 执行 yt-dlp 命令
       └─ update_user_config_file()          # 更新用户配置文件
```

### API 请求

**微博列表**：`GET https://m.weibo.cn/api/container/getIndex`
- 普通模式：`containerid=230413{user_id}`
- 搜索模式：`container_ext=profile_uid:{user_id}&containerid=100103type=401&q={query}`
- 参数：`page`, `count`

**用户信息**：`GET https://m.weibo.cn/api/container/getIndex`
- `containerid=100505{user_id}` → 基本信息
- `containerid=230283{user_id}_-_INFO` → 详细信息（生日/所在地/教育等）

**长微博**：`GET https://m.weibo.cn/detail/{id}`
- 从 HTML 中提取 `"status":{...},"call"` 之间的 JSON

**评论**：
- 有 Cookie：`GET https://m.weibo.cn/comments/hotflow?mid={id}&max_id={max_id}`
- 无 Cookie：`GET https://m.weibo.cn/api/comments/show?id={id}&page={page}`

**转发**：`GET https://m.weibo.cn/api/statuses/repostTimeline?id={id}&page={page}`

### 重试与验证码

- 最大重试 5 次，指数退避（`5 * 2^retries` 秒）
- 检测到验证码 → `handle_captcha()` 打开浏览器让用户手动验证
- 每个用户前随机 sleep 30-60 秒

---

## 微博解析 (`parse_weibo`)

从 API 返回的 `mblog` 对象提取：

| 字段 | 来源 |
|------|------|
| `user_id` / `screen_name` | `weibo_info["user"]` |
| `id` / `bid` | `weibo_info["id"]` / `weibo_info["bid"]` |
| `text` | `weibo_info["text"]`（可选移除 HTML 标签） |
| `pics` | `get_pics()` — 图片 URL 逗号分隔 |
| `video_url` | `get_video_url()` — 视频 URL 分号分隔 |
| `live_photo_url` | `get_live_photo_url()` — Live Photo URL 分号分隔 |
| `links` | `get_link_urls()` — 正文中的链接 |
| `location` | `get_location()` — 发布位置 |
| `created_at` | 原始时间 → `standardize_date()` 标准化 |
| `topics` | `get_topics()` — #话题# |
| `at_users` | `get_at_users()` — @用户 |

### 图片提取 (`get_pics`)

1. 遍历 `weibo_info["pics"]`，跳过 `type=video` 的条目
2. 取 `pic["large"]["url"]`，替换路径中的尺寸标识为 `/large/`（确保原图）
3. 兼容正文内嵌图片链接（`get_inline_image_urls`）

### 视频提取 (`get_video_url`)

1. 优先从 `pics` 中提取 `type=video` 的 `videoSrc`
2. 回退到 `page_info`：
   - 优先 `page_url`（`video.weibo.com/show?fid=xxx` 格式，用于 yt-dlp）
   - 回退 `media_info` 中的直接下载地址（优先级：720p > hd > sd）

### Live Photo 提取 (`get_live_photo_url`)

直接从 `weibo_info["live_photo"]` 数组获取，分号分隔。

---

## 文件命名规则

### handle_download 中的命名（img/video/live_photo）

**文件前缀**：`{YYYYMMDD}_{微博ID}`
- `created_at[:11].replace("-", "")` → `YYYYMMDD`
- `str(w["id"])` → 微博 ID

**图片**：
- 单张：`{前缀}{后缀}`（后缀从 URL 推断，≥5 字符则用 `.jpg`）
- 多张：`{前缀}_{序号}{后缀}`

**视频**：
- 单个：`{前缀}.mp4`
- 多个：`{前缀}_{序号}.mp4`
- `video.weibo.com/show` 链接 → 调用 yt-dlp，扩展名由 yt-dlp 决定

**Live Photo**：
- 单个：`{前缀}.mp4`（`.mov` 结尾的 URL 用 `.mov`）
- 多个：`{前缀}_{序号}.{mp4/mov}`

### Markdown 中的图片命名 (`_download_weibo_images`)

**文件名**：`{YYYY-MM-DD}_{HH-MM-SS}_{序号}.jpg`
- 时间来自 `created_at`（ISO 格式解析）
- 多张图片追加 `_1`, `_2` 后缀

### get_download_file_names（供 Markdown 链接使用）

与 `handle_download` 相同的前缀逻辑，但仅返回文件名列表不实际下载。

---

## Markdown 生成逻辑

### 分组方式 (`markdown_split_by`)

| 值 | 文件路径 | 标题格式 |
|----|----------|----------|
| `day` | `{YYYY-MM-DD}.md` | 仅时间 `HH:MM:SS` |
| `day_by_month` | `{YYYY-MM}/{YYYY-MM-DD}.md` | 仅时间 |
| `month` | `{YYYY-MM}.md` | 完整日期时间 |
| `year` | `{YYYY}.md` | 完整日期时间 |
| `all` | `{昵称}.md` | 完整日期时间 |

### 微博条目格式

```markdown
### {时间}
<!-- weibo_id: {微博ID} -->
{正文}

![img](img/{图片文件名})

[视频](原创微博视频/{视频文件名})

[Live Photo](原创微博Live Photo视频/{Live Photo文件名})

---
```

转发微博的转发部分以引用块（`>`）呈现。

### 增量写入

- 读取已有 MD 文件，提取所有 `<!-- weibo_id: xxx -->` 去重
- 新微博追加到文件末尾
- 新文件添加标题行 `## {日期} [{用户名}] 微博存档`

### 正文渲染 (`render_markdown_text`)

- `网页链接` → `[网页链接](url)`
- `查看图片` → `![查看图片](img/文件名)`

---

## 下载逻辑

### download_one_file

1. 跳过无效 URL（非 http/https 开头）
2. 文件已存在则跳过
3. 流式下载，60 秒无数据判定为停滞
4. Magic Number 检测文件类型：
   - `FF D8 FF` → JPEG（验证末尾 `FF D9`）
   - `89 PNG` → PNG（验证末尾 `IEND`）
   - `ftyp` → MP4/MOV
5. 动态调整扩展名
6. JPG 写入 EXIF 时间（`write_time_in_exif`）
7. 所有文件修改系统时间（`change_file_time`）
8. 失败记录到 `not_downloaded.txt`

### yt-dlp 视频下载 (`yd_video_file`)

- `video.weibo.com/show?fid=xxx` 链接不直接下载
- 命令写入 `yt-dlp_commands.txt`
- 当前用户处理完后统一执行（`execute_stored_video_downloads`）

---

## 数据持久化

### CSV

- 用户信息 → `users.csv`
- 微博信息 → `{user_id}.csv`
- 评论导出 → `{昵称}_comments.csv` + 按微博拆分 `{昵称}_{weibo_id}_comments.csv`

### JSON

- 合并更新：已存在的微博更新为最新值，新微博追加

### SQLite

**表结构**：
- `user`：id, nick_name, gender, follower_count, ip_location, ...
- `weibo`：id, bid, user_id, text, pics, video_url, live_photo_url, edited, edit_count, ...
- `comments`：id, weibo_id, user_screen_name, text, pic_url, ...
- `reposts`：id, weibo_id, user_screen_name, text, ...
- `bins`：id, ext, data(blob), weibo_id, path, url

**自动迁移**：`update_sqlite_table` 检测并添加缺失字段（ip_location, edited, edit_count）

### MySQL / MongoDB / POST

- MySQL：自动建库建表，INSERT OR UPDATE
- MongoDB：`find_one` + `insert_one` / `update_one`
- POST：通过 API Token 发送 JSON

---

## 运行模式 (`const.py`)

| 模式 | 说明 |
|------|------|
| `overwrite` | 每次全量爬取 |
| `append` | 增量模式，仅 SQLite 可用。记录上次微博 ID，只获取新增 |

### Cookie 检查

`const.CHECK_COOKIE`：通过检测仅自己可见的微博是否存在来验证 Cookie 有效性。

---

## 辅助脚本

### rename_files.py

独立脚本，将已下载的媒体文件按 `{YYYYMMDD}_{正文前50字符}_{微博ID}_{序号}.{后缀}` 规则重命名，并同步更新 Markdown 中的引用路径和 Live Photo 排列顺序。

**完整处理流程**（`process_user_dir`）：

1. 解析 Markdown 文件，提取每条微博的元数据（时间戳、weibo_id、正文）
2. 扫描磁盘文件，通过时间戳前缀或微博 ID 匹配媒体文件
3. 按规则生成新文件名并执行重命名（`execute_rename`）
4. 更新 Markdown 中的媒体引用路径（`update_md_references`）
   - 图片保持 `![img](path)` 语法
   - 视频文件（.mov/.mp4）自动转换为 `<video src="path" controls></video>` 嵌入语法
5. 调整 Live Photo 顺序（`reorder_live_photos`）
   - 将散落在图片列表之后的 `<video>` 标签移到对应同名图片下方
   - 用 `<!-- processed_live_photo -->` HTML 注释标记已处理的图文对，确保幂等

**关键函数**：

| 函数 | 职责 |
|------|------|
| `parse_md_sections` | 解析 Markdown，按 `### 时间 / <!-- weibo_id -->` 分段提取元数据 |
| `_extract_text_from_body` | 从正文中提取纯文本，跳过媒体行和 HTML 注释行 |
| `sanitize_text` | 清理文本用于文件名：去除 HTML 注释、非法字符、截断至 50 字符 |
| `build_disk_index` | 扫描用户目录下所有媒体文件，建立文件名索引 |
| `find_files_for_section` | 通过时间戳前缀或微博 ID 匹配磁盘文件 |
| `build_rename_plan` | 为所有微博段构建重命名计划，按目录+扩展名分组分配序号 |
| `update_md_references` | 按微博段逐段重建引用路径，视频文件转为 `<video>` 嵌入语法 |
| `reorder_live_photos` | 将 Live Photo 视频标签移到同名图片下方，支持幂等重复执行 |

**命令**：
- `python rename_files.py preview <目录>` — 预览模式，不实际改名
- `python rename_files.py apply <目录>` — 实际执行改名

### test_weibo.py

单条微博测试脚本，读取 `config.json` 配置，指定微博 ID 下载到 `test` 目录。

### download_single_video.py

单视频下载工具，用于补下载失败的视频。
