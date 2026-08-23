# 阿里云服务器一键部署交接

## 已知前提

- 服务器：`121.199.52.72`
- 系统要求：Ubuntu 22.04+，root 权限
- 阿里云安全组放行 TCP `80`
- PostgreSQL 数据库 `enrui_ai_commerce_agent` 与 37 张业务表已经初始化
- 不需要建库、建表、执行 SQL、迁移或处理本地业务数据
- 生产配置只保存在服务器 `/opt/enrui-ai-commerce-agent/shared/.env`

## 首次部署

```bash
git clone https://github.com/Dreamsmama/enrui-ai-commerce-agent.git /opt/enrui-ai-commerce-agent/repository
bash /opt/enrui-ai-commerce-agent/repository/deploy.sh
```

第一次执行会创建 `/opt/enrui-ai-commerce-agent/shared/.env` 并退出。编辑该文件，填写所有 `FILL_` 项，然后再次执行：

```bash
bash /opt/enrui-ai-commerce-agent/repository/deploy.sh
```

脚本会自动安装 Git/Docker（缺失时）、拉取 `main` 最新提交、构建前后端镜像、执行 PostgreSQL/Redis/OSS 幂等检查、替换旧容器并访问 `/api/health`。部署日志保存在 `/opt/enrui-ai-commerce-agent/shared/logs/`。

## 后续更新

代码推送到 `main` 后，服务器只需重复执行：

```bash
bash /opt/enrui-ai-commerce-agent/repository/deploy.sh
```

脚本会记录 Git 提交 ID。若新版本健康检查失败，会自动恢复上一次运行中的镜像；回退失败时会保留容器日志并返回非零退出码。

## 验收回执

部署完成后请回复：

1. 公网访问地址（通常为 `http://121.199.52.72`）
2. 部署的 Git 提交 ID
3. `curl http://127.0.0.1/api/health` 的完整结果（应包含 `database=postgresql`、`redis=ok`、`storage=aliyun_oss`）
4. `docker compose ps` 中前后端容器均为 `Up`/健康

生产密码、Aliyun AccessKey、LLM/API Key 只写入服务器 `.env`，不要发群聊或提交 Git。
