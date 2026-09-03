# 升级说明（2026-08-28）

本次升级分支：`upgrade/2026-08-28`。

## 1. anthropic SDK 0.39 → 1.1.0

- `app/services/analysis.py` 改用 `AsyncAnthropic` 异步客户端并 `await client.messages.create(...)`。
  旧代码在 async 函数里调用同步客户端，会阻塞事件循环（上传接口和状态轮询会被分析请求卡住），
  这次一并修复。
- `messages.create` 的参数（model / max_tokens / messages）在 1.x 中不变，无需改动调用形态。
- 错误处理从裸 `except Exception` 细化为 1.x 错误层级：
  `APIConnectionError`（网络）、`APIStatusError`（HTTP 4xx/5xx，含 `RateLimitError` 等子类）、
  兜底 `AnthropicError`，统一包装为业务侧的 `AnalysisError`。
- 响应文本提取改为遍历 `message.content` 中 `type == "text"` 的 block（`_extract_text`），
  不再假设 `content[0]` 一定是文本。
- 未使用 streaming，无需迁移。
- 模型名保持 `claude-sonnet-4-20250514`（集中到 `CLAUDE_MODEL` 常量，便于后续升级模型）。

## 2. 其余依赖（保守：仅在当前小版本内升到最新 patch）

| 包 | 旧 | 新 | 备注 |
|---|---|---|---|
| fastapi | 0.115.0 | 0.115.14 | 同小版本 patch |
| uvicorn | 0.30.0 | 0.30.6 | patch |
| jinja2 | 3.1.4 | 3.1.6 | 含安全修复 |
| python-multipart | 0.0.9 | 0.0.20 | 含 DoS 安全修复 |
| httpx | 0.27.0 | 0.27.2 | 原文件重复声明两次，已去重 |
| pytest | 8.3.3 | 8.3.5 | patch |
| supabase | 2.9.1 | 2.9.1 | 2.9.x 内已是最新；上游最新为 2.31.x，跨度大，留待单独升级 |
| pydantic | （未固定） | 2.13.4 | 显式固定，避免隐式漂移 |
| itsdangerous | （缺失） | 2.2.0 | `SessionMiddleware` 的必需依赖，原 requirements 漏掉，属修复 |

fastapi 0.115 → 0.141、supabase 2.9 → 2.31 属于跨小版本升级，改动面大，
建议在 CI 稳定后单独开分支验证（supabase 2.2x 起 `gotrue` 更名 `supabase_auth`，
当前已能看到 DeprecationWarning）。

## 3. CI

新增 `.github/workflows/ci.yml`：push / PR 触发，Python 3.11，
`ruff check .` + `pytest -q`。ruff 规则见 `pyproject.toml`（E/F/W，忽略 E501）。
测试不访问外部服务：Claude 调用在 `tests/test_analysis.py` 中 monkeypatch mock，
Supabase / ASR 无单元测试覆盖（客户端均为惰性初始化，导入安全）。

## 4. 后台任务：从 asyncio.create_task 迁移到任务队列

现状：`app/main.py` 用 `asyncio.create_task` 在 Web 进程内跑
转写→分析→更新 playbook 流水线（不是 FastAPI 的 `BackgroundTasks`，本质相同）。
问题：进程重启即丢任务；多 worker（uvicorn --workers / k8s 多副本）下无法协调；
无重试与并发限制。当前靠 `check_stale_recordings` 的 10 分钟超时兜底把卡住的录音标为 failed。

推荐方案：**arq**（基于 asyncio + Redis，改动最小）

1. 依赖：`pip install arq redis`，部署一个 Redis。
2. 新建 `app/worker.py`，把 `process_recording` / `process_transcript` 注册为 arq 任务函数
   （它们已经是 async 函数，签名基本不用改，`ctx` 参数加在首位即可）。
3. `app/main.py` 三处 `asyncio.create_task(...)`（已标 TODO）替换为
   `await request.app.state.arq.enqueue_job("process_recording", recording_id, audio_url)`；
   arq 连接池在 lifespan 中创建/关闭。
4. `periodic_stale_check` 移到 arq 的 `cron_jobs`（每分钟），Web 进程不再跑循环。
5. 部署新增进程：`arq app.worker.WorkerSettings`；配置 `max_tries`（建议 3）与
   `job_timeout`（对齐 PROCESSING_TIMEOUT_MINUTES）。
6. 注意：签名 URL 需在任务执行时生成（或有效期覆盖排队+处理时间），
   建议把 `storage_path` 而非 URL 作为任务参数，worker 内再调 `db.get_audio_url()`。

备选 celery：生态更全（flower 监控、多队列），但任务函数需要同步化或用
`asyncio.run` 包装，对本项目纯 async 代码侵入更大。单机单用户阶段 arq 足够。

## 5. audio bucket 私有化 + 签名 URL

原实现：README 要求建 **public** bucket，代码用 `get_public_url()` 生成永久公开链接给 ASR。
风险：任何拿到 URL 的人都能下载客户通话录音（含个人隐私），且链接永不过期。

**代码已改**（向后兼容，公开 bucket 上签名 URL 同样有效）：

- `app/database.py` 新增 `get_audio_url(storage_path, expires_in=3600)`，
  内部走 `storage.from_("audio").create_signed_url()`。
- `app/main.py` 上传与重试两处不再调用 `get_public_url`。
- 音频 URL 只在生成后传给 ASR 一次性使用，1 小时有效期覆盖处理窗口
  （处理超时上限为 10 分钟）；前端页面不直接引用音频 URL，无其他破坏点。

**存量环境操作步骤**（Supabase 控制台）：

1. Storage → `audio` bucket → 设置里关闭 "Public bucket"。
2. 确认 RLS：私有 bucket 默认仅 service role 可读写；本应用服务端持
   `SUPABASE_KEY`（service role）即可，无需额外 policy。
3. 验证：上传一条新录音走完整流水线；对旧录音点"重试"验证签名 URL 路径。
4. 旧的 public URL 在 bucket 关闭公开后自动失效，无需逐个清理。

## 6. 密钥管理

代码中无硬编码密钥（全部走 `app/config.py` 的环境变量）。
补上了 README 引用但缺失的 `.env.example`。`.gitignore` 已忽略 `.env`。
