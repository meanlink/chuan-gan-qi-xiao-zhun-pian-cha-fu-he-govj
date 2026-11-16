# 传感器校准偏差复核

Bootstrap 区间估计的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery。

### 时区化排期（海外实验室当地日历）
分发计划支持两种模式，旧固定秒数计划保持原逻辑照常运行：
- `weekly`（推荐）：IANA 时区 + 每周日期（ISO 周一至周日）+ 当地时分，按当地挂钟时间换算 UTC 绝对时刻。
- `interval`（旧）：固定 `interval_seconds` 秒数，行为与历史版本一致。

夏令时由 `zoneinfo` 处理：春令时跳空导致当地时刻不存在时，该场标记 `skipped` 不发送；秋令时重叠的当地时刻只取 fold=0 的第一次，重复时刻不发第二次。

排期采用版本化场次模型：
- `ScheduleVersion` 为不可变版本（时区、周几、时分、生效点）；改期即新增版本，生效点之后尚未落地的场次按新版本重建，生效点之前的场次（含欠发）保留在原版本上补发，旧执行晚到也归档到原版本，不串入新排期。
- `Occurrence` 记录每一场：原定 UTC 时刻、当地日期/时刻、时区、所属版本、状态（pending/claimed/delivered/skipped）与领取轨迹。
- 停机后 worker 逐场补齐所有到期欠发；进程崩溃后超时的 claimed 场次自动恢复为 pending 并保留原场次记录；归档与场次一一对应，重试复用不新增；多执行者通过条件更新原子争领，同一场只被一方领取与归档。
- 每份 Delivery 归档保留原定当地时间（scheduled_local）、实际归档时间（created_at）与排期版本号（schedule_version）。

页面「分发档案」可预览后续场次（含 DST 跳过标记）、创建/暂停计划、按生效点改期，并逐场核对欠发、补发与归档结果。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18206；后端文档 http://localhost:19206/docs；数据库宿主端口 17706。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；PostgreSQL 16；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=sensor-bootstrap；FRONTEND_PORT=18206；BACKEND_PORT=19206；DB_PORT=17706；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按到期场次（weekly）或 next_run（interval）生成本地收件箱文件。周期 60 秒至 30 天（仅 interval 模式）。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1007/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
