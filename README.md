# 销冠克隆器 (Sales Champion Cloner)

将销冠的销售通话录音转化为结构化的知识库，帮助团队复制顶级销售的能力。

## Phase A: 销冠镜子

当前阶段为验证期，核心功能：
- 上传销售通话录音
- AI自动转写（含说话人分离）
- 深度分析销售模式（通话阶段、异议处理、成交技巧）
- 跨录音生成Playbook（增量更新）

## Tech Stack

- **Backend:** Python FastAPI + Jinja2
- **ASR:** Alibaba Cloud Speech API (hosted)
- **Analysis:** Claude API (Anthropic)
- **Database:** Supabase (Postgres + Storage)
- **Deploy:** Railway / Docker

## Setup

```bash
# Clone
git clone https://github.com/hanxiao199001/sales-champion-cloner.git
cd sales-champion-cloner

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Run
python -m app.main
```

## Supabase Setup

Create these tables in your Supabase project:

```sql
CREATE TABLE recordings (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    transcript JSONB,
    analysis JSONB,
    asr_confidence FLOAT,
    error_message TEXT
);

CREATE TABLE playbook_patterns (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    frequency INT DEFAULT 1,
    example_quotes JSONB DEFAULT '[]',
    description TEXT,
    source_recording_ids JSONB DEFAULT '[]',
    boss_annotation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(category, name)
);
```

Also create a Storage bucket named `audio` with public access.

## Architecture

```
Browser (老板) → FastAPI (单体) → Supabase Storage (音频)
                     ↓
              Background Task
              ├── ASR API (转写+分离)
              └── Claude API (分析)
                     ↓
              Supabase Postgres (数据)
```

## License

MIT
