# 数据库结构说明（SQLite）

本项目使用 SQLite，默认库文件为 `paper_serch.db`（可用 `.env` 的 `PAPER_SERCH_DB_PATH` 覆盖）。
应用启动时会在 `app/core/db.py:init_db()` 自动创建表，并对新增字段做轻量级迁移（`ALTER TABLE ... ADD COLUMN`）。

## 配置优先级（AI）

同一类 AI 配置的覆盖顺序为：

1. 管理员在页面表单中临时填写的参数（仅对本次请求生效，不落库）。
2. 管理面板 `/admin/users` 为该用户保存的参数（`users.ai_*`）。
3. `.env` / 环境变量中的全局预设（例如 `PRESET_AI_PROVIDER`、`OPENAI_*`、`GEMINI_*`）。

## 表：`users`

用户基础信息（账号、权限、偏好配置）。

- `id`：主键，自增。
- `email`：唯一邮箱（登录名）。
- `password_hash`：密码哈希（Werkzeug）。
- `is_admin`：是否管理员（`0/1`）。
- `ai_provider`：为该用户固定的 AI Provider（`openai/gemini` 或空字符串表示“跟随环境预设”）。
- `ai_model`：为该用户固定的模型名（空字符串表示使用 Provider 默认模型）。
- `ai_api_key`：为该用户固定的 API Key（空字符串表示从环境变量读取）。
- `ai_base_url`：为该用户固定的 Base URL（空字符串表示从环境变量读取；主要用于 OpenAI 兼容接口）。
- `workflow_max_directions`：自动工作流单次最多提取方向数（默认 6）。
- `workflow_max_results_per_direction`：自动工作流每个方向最多抓取文献数（默认 3）。
- `created_at`：创建时间（UTC ISO 字符串）。

## 表：`accounts`

用户账户与次数额度（与 `users` 一对一）。

- `user_id`：主键，同时是外键引用 `users.id`。
- `credits_balance`：剩余自动工作流次数。
- `credits_unlimited`：是否不消耗次数（管理员为 `1`；普通用户为 `0`）。
- `updated_at`：最近一次变更时间（UTC ISO 字符串）。

## 表：`workflow_runs`

自动工作流运行记录（用于“账户”页展示与排错）。

- `id`：主键（UUID 字符串）。
- `user_id`：外键，所属用户。
- `status`：`running/succeeded/failed`。
- `created_at` / `started_at` / `finished_at`：时间戳（UTC ISO 字符串）。
- `input_hash`：输入内容哈希（用于定位相同输入）。
- `config_json`：当次工作流参数快照（JSON 字符串）。
- `error_message`：失败原因（截断保存）。

## 表：`credit_ledger`

次数变更流水（扣费/充值/管理员调整）。

- `id`：主键（UUID 字符串）。
- `user_id`：外键，所属用户。
- `workflow_run_id`：可选外键，关联一次工作流。
- `entry_type`：`credit/debit/info`（管理员不消耗次数时会记录为 `info`）。
- `units`：变动单位数（管理员不消耗次数时为 `0`）。
- `reason`：原因（例如 `workflow_consumption` / `admin_adjustment`）。
- `idempotency_key`：幂等键（用于避免重复扣费）。
- `created_at`：时间戳（UTC ISO 字符串）。
- `metadata_json`：可选元数据（JSON 字符串）。

索引：
- `idx_credit_ledger_workflow_once`：对 `workflow_consumption` 做唯一约束，防止同一 `workflow_run` 重复扣费。
