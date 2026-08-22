# 阿里云单环境配置

本项目使用一个共享环境：PostgreSQL 保存业务事实和持久任务，Redis 用于队列唤醒、分布式任务锁和并发协调，OSS 是所有上传与生成文件的唯一持久存储。本地只使用操作系统临时目录作为可重建处理缓存。

## 新资源命名

- PostgreSQL 数据库：`enrui_ai_commerce_agent`
- OSS 目录前缀：`enrui-ai-commerce-agent/`
- Redis Key 前缀：`enrui-ai-commerce-agent:`

## 同事需提供的配置

请通过密码管理器传递，不要发到聊天、工单或提交到 Git：

```dotenv
# 必须是拥有 CREATE DATABASE 权限的连接，仅初始化时使用
POSTGRES_ADMIN_URL=postgresql://<admin-user>:<url-encoded-password>@121.199.52.72:5432/postgres

# 应用运行连接；可以先沿用现有账号，建议后续建立最小权限专用账号
DATABASE_URL=postgresql+psycopg://<app-user>:<url-encoded-password>@121.199.52.72:5432/enrui_ai_commerce_agent

REDIS_URL=redis://121.199.52.72:6379/0
REDIS_KEY_PREFIX=enrui-ai-commerce-agent:

ALIYUN_OSS_REGION=oss-cn-hangzhou
ALIYUN_OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
ALIYUN_OSS_ACCESS_KEY_ID=<new-access-key-id>
ALIYUN_OSS_ACCESS_KEY_SECRET=<new-access-key-secret>
ALIYUN_OSS_BUCKET_NAME=commerce-agent-raw
ALIYUN_OSS_PREFIX=enrui-ai-commerce-agent/
STORAGE_PROVIDER=aliyun_oss
```

OSS RAM 账号至少需要对 `commerce-agent-raw/enrui-ai-commerce-agent/*` 执行 PutObject、GetObject、DeleteObject、ListObjects 的权限。公网 PostgreSQL 与 Redis 的安全组只允许应用服务器和开发机固定出口 IP；Redis 必须尽快启用密码或 ACL。

## 初始化

先在 `backend/.env` 配置应用变量。管理员连接只在当前终端临时设置，然后运行：

```bash
cd backend
python -m pip install -r requirements.txt
POSTGRES_ADMIN_URL='...' python scripts/bootstrap_aliyun.py
python scripts/init_deployment.py
```

`init_deployment.py` 可重复执行：它会连接线上 PostgreSQL、创建当前代码模型声明的全部业务表，并校验是否缺表。当前没有必须预置的业务数据；企业和首位 Owner 通过注册接口创建。本地业务数据不在部署时迁移，后续如需迁移应使用单独的数据迁移任务。

最后启动服务，访问 `/api/health`，确认 `database=postgresql`、`redis=ok`、`storage=aliyun_oss`。
