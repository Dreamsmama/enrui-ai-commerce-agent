# Enrui AI Commerce Agent 部署交接单

## 一、目标

将 GitHub 仓库 `Dreamsmama/enrui-ai-commerce-agent` 的 `main` 分支一键部署到阿里云 Ubuntu 22.04 服务器，并确认网页和后端服务正常运行。

目标服务器：`121.199.52.72`。

## 二、已经完成的部分

项目侧已经具备以下部署能力，同事不需要重新设计部署架构：

- 前端 React 生产构建及 Nginx 托管。
- FastAPI 后端 Docker 镜像。
- Docker Compose 前后端编排及自动重启。
- Nginx `/api` 反向代理和前端 SPA 路由。
- PostgreSQL 线上业务库连接及37张业务表自动初始化。
- Redis队列唤醒、分布式任务锁和并发协调。
- 阿里云OSS主存储、签名访问和临时处理缓存。
- 部署前强制检查PostgreSQL、Redis、OSS，任意服务不可用即停止部署。
- 自动拉取 `main` 最新代码、构建镜像、更新容器和健康检查。
- 生产密钥独立保存在服务器，不进入Git仓库。

线上数据库 `enrui_ai_commerce_agent` 及现有37张业务表已经初始化完成。同事不需要建库、手工建表、执行SQL或迁移本地数据。部署脚本中的数据库步骤只进行幂等结构检查：已有表不会重复创建、清空或覆盖。

核心部署入口：

```text
/opt/enrui-ai-commerce-agent/repository/deploy.sh
```

生产配置位置：

```text
/opt/enrui-ai-commerce-agent/shared/.env
```

## 三、同事需要完成的工作

### 1. 检查服务器

使用root登录服务器，确认80端口没有被其他项目占用：

```bash
ss -ltnp | grep ':80 ' || true
df -h /
free -h
```

如果80端口已有服务，先确认它属于哪个项目，不要直接停止或删除，联系项目负责人决定端口或Nginx合并方案。

阿里云安全组至少需要开放：

```text
TCP 80：网页访问
TCP 22：运维SSH，建议只允许办公网络固定IP
```

PostgreSQL、Redis不需要继续向所有公网IP开放，只保留应用服务器和必要开发出口IP。

### 2. 首次初始化

```bash
git clone https://github.com/Dreamsmama/enrui-ai-commerce-agent.git /opt/enrui-ai-commerce-agent/repository
bash /opt/enrui-ai-commerce-agent/repository/deploy.sh
```

脚本会自动安装Git和Docker。首次运行会生成生产配置文件并主动停止，这是正常行为。

### 3. 填写服务器运行配置

编辑：

```bash
nano /opt/enrui-ai-commerce-agent/shared/.env
```

必须填写或确认：

- `DATABASE_URL`：确认指向已经建好的线上 `enrui_ai_commerce_agent`，不要改成 `canvas_platform` 或SQLite。
- `REDIS_URL`：线上Redis连接串。
- `ALIYUN_OSS_ACCESS_KEY_ID`：轮换后的OSS RAM AccessKey。
- `ALIYUN_OSS_ACCESS_KEY_SECRET`：轮换后的OSS RAM Secret。
- `AUTH_SECRET`：执行 `openssl rand -hex 32` 生成，不能使用默认值。
- `LLM_API_KEY`、`LLM_MODEL`、`LLM_VISION_MODEL`：实际大模型配置。
- `IMAGE_GENERATION_API_KEY`、`IMAGE_GENERATION_MODEL`：火山方舟Seedream配置。

检查不能残留占位符：

```bash
grep -n 'FILL_' /opt/enrui-ai-commerce-agent/shared/.env
```

正确结果应当没有任何输出。不要把生产 `.env` 发到群里、提交到Git或复制到工单。

### 4. 正式部署

```bash
bash /opt/enrui-ai-commerce-agent/repository/deploy.sh
```

脚本会依次执行：拉取最新代码、构建镜像、幂等检查现有数据库表及线上服务连接、启动容器、执行健康检查。无需额外执行建库、建表或数据迁移命令。

### 5. 验收

```bash
cd /opt/enrui-ai-commerce-agent/repository
docker compose ps || docker-compose ps
curl -fsS http://127.0.0.1/api/health
```

健康接口应至少满足：

```text
status=ok
database=postgresql
redis=ok
storage=aliyun_oss
```

浏览器访问：

```text
http://121.199.52.72
```

完成基础部署验收：

1. 公网打开登录页面，静态资源加载正常。
2. 调用 `/api/health`，确认PostgreSQL、Redis和OSS状态正常。
3. 登录一个已有账号；如果线上还没有账号，再注册首个企业Owner。
4. 页面刷新和前端路由跳转不出现404。

## 四、以后更新代码

代码push到 `main` 后，只运行：

```bash
bash /opt/enrui-ai-commerce-agent/repository/deploy.sh
```

不要删除 `/opt/enrui-ai-commerce-agent/shared/.env`。它独立于仓库，不会被 `git pull` 覆盖。

## 五、失败时回传信息

请不要只回复“部署失败”。回传以下脱敏结果，禁止包含 `.env`、密码、AccessKey和API Key：

```bash
cd /opt/enrui-ai-commerce-agent/repository
docker compose ps || docker-compose ps
docker compose logs --tail=200 backend frontend 2>&1 || docker-compose logs --tail=200 backend frontend 2>&1
curl -i http://127.0.0.1/api/health
```

同时说明：

- 执行到哪一步失败。
- 完整错误时间。
- 80端口是否已被占用。
- 阿里云安全组是否已开放80端口。
- 最近一次部署对应的Git提交ID：`git rev-parse HEAD`。

## 六、完成标准

满足以下全部条件才算完成：

- 前后端容器状态正常且设置自动重启。
- 公网可以打开登录页面。
- 健康接口显示PostgreSQL、Redis、OSS均正常。
- 上传文件实际进入OSS，而不是服务器持久目录。
- 线上PostgreSQL连接正常，部署过程没有修改或迁移既有业务数据。
- 生产 `.env` 权限为600且未进入Git。
- 将访问地址、部署提交ID和验收结果回复项目负责人。
