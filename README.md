# feishu-laser-dxf-bot

一个飞书(Lark)机器人。在飞书聊天里发一条带 `/dxf` 和图片的消息,机器人会自动用 AI 把图片里的 logo 抠干净、摆正、改成黑底白图,然后转成激光打标用的 DXF 文件发回来。回复里会带:清理后的图片 + 转换预览图 + DXF 文件 + 一句话摘要。

底层依赖:

- [`image-to-laser-dxf`](https://github.com/yang362323/image-to-laser-dxf) — 把位图转成 DXF(本机包)
- [豆包 Seedream](https://www.volcengine.com/product/ark) — 把原图先做 AI 标准化(通过火山引擎 Ark API)

适合 2-5 人的小团队共用一个机器人,跑在一台云服务器上。

## 工作流程

用户在飞书里发一条带 `/dxf` 文字 + 一张图片的消息(可以跟机器人私聊,也可以在群里),机器人会:

1. 回复"正在处理..."(进度提示 1)
2. 从飞书下载原图
3. 回复"正在清理图片..."
4. 调豆包 Seedream 把图片标准化:提高清晰度、摆正 logo、把 logo 改成纯黑、背景改成纯白
5. (如果豆包返回慢,再发一条"正在转换 DXF..."避免卡住错觉)
6. 把清理后的图片上传到飞书,得到 image_key
7. 用 `image_to_dxf.convert` 把清理后的 PNG 转成 DXF
8. 用 ezdxf + matplotlib 渲染一张预览 PNG,上传,得到 image_key
9. 把 DXF 文件上传,得到 file_key
10. 发一条富文本消息(标题"转换结果"),包含:摘要文字 + 清理后的图片 + 预览图 + DXF 文件

如果中间任意一步失败,会发一条短中文消息提示用户(比如"图片下载失败,请重试")。

所有转换参数都用 `image_to_dxf` 的默认(`px_to_mm=0.05`、blur=5、morph=3 等),暂不开放自定义。

## 项目结构

```
app/
  main.py              # 入口:装配 lark WS 客户端 + FastAPI /healthz
  config.py            # 从环境变量读配置
  handlers.py          # /dxf 编排器(整条流水线的核心)
  feishu_client.py     # 对 lark_oapi 的类型化封装
  converter.py         # 包装 image_to_dxf.convert
  preview.py           # DXF -> PNG 渲染
  doubao_normalizer.py # 豆包 Ark 客户端 + 重试策略
  doubao_prompt.py     # 固定的豆包提示词
tests/                 # pytest 测试套件
docs/superpowers/      # 设计规格 + 实现计划
Dockerfile
docker-compose.yml
```

## 飞书后台配置(首次部署一次性操作)

1. 打开 https://open.feishu.cn/ ,创建企业自建应用
2. 添加 **Bot** 能力
3. **权限管理** 里开通以下权限:
   - `im:message`
   - `im:message:send_as_bot`
   - `im:message.group_at_msg`
   - `im:message.p2p_msg`
   - `im:resource`
4. **事件订阅** 里订阅 `im.message.receive_v1` 事件(接收消息)。lark-oapi 的 WebSocket 客户端会在应用发布后自动接收这些事件
5. 在 **机器人能力** 里可以配置一个 `/dxf` 斜杠指令菜单(可选,只是让用户输入 `/` 时弹出提示;不配的话用户也可以手动输入 `/dxf`)
6. 复制 **App ID** 和 **App Secret** 到 `.env`
7. 在飞书里搜机器人名字,加好友或拉到群里,发消息测试

> 关于事件类型:用户点击 `/dxf` 菜单后,菜单只是把 `/dxf` 文本插入到输入框,用户再附图发送。整个消息(含图片)作为普通的 `im.message.receive_v1` 事件到达机器人,**不是** `application.bot.menu_v6` 事件。

## 火山引擎 Ark 配置(Doubao 标准化)

1. 打开 https://www.volcengine.com/ ,开通方舟(Ark)服务
2. 开通 Seedream 文生图/图编辑模型(本项目默认 `doubao-seedream-4-0-250828`)
3. 在 **API Key 管理** 创建一个 API Key
4. 把 API Key 填到 `.env` 的 `ARK_API_KEY=...`

如果只测转 DXF(不想调 AI 标准化),可以把 `app/handlers.py` 里 `doubao_normalizer.run(...)` 那一段改回直接传原图。本项目当前默认是必须开 AI 标准化。

## 本地开发

需要 Python 3.11(项目用 `requires-python = ">=3.11"`)。

```bash
git clone https://github.com/yang362323/feishu-laser-dxf-bot
cd feishu-laser-dxf-bot

python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ../image-to-laser-dxf       # 本地包依赖

cp .env.example .env                       # 然后编辑 .env 填真实凭证
pytest -v                                   # 跑全部测试
```

烟测健康检查端点(用假凭证即可;WS 会连不上,但 HTTP 服务能起):

```bash
FEISHU_APP_ID=cli_x FEISHU_APP_SECRET=y ARK_API_KEY=ark-fake \
    .venv/bin/python -m app.main &
sleep 3
curl http://localhost:8080/healthz         # → {"status":"ok"}
kill %1
```

## 部署

云服务器上(假设已装好 Docker 和 docker compose):

```bash
git clone https://github.com/yang362323/feishu-laser-dxf-bot
cd feishu-laser-dxf-bot
cp .env.example .env
# 编辑 .env,填入:
#   FEISHU_APP_ID / FEISHU_APP_SECRET(从飞书后台拿)
#   ARK_API_KEY(从火山引擎 Ark 后台拿)

docker compose up -d --build
docker compose logs -f bot                 # 看启动日志
docker compose ps                          # 应该显示 healthy
```

第一次 build 时,Dockerfile 会从 GitHub 拉取 `image-to-laser-dxf` 的最新 main 分支并安装。要固定版本,在 `docker-compose.yml` 里改 `ITD_REF` 那个构建参数(比如改成 `v0.1.0`)。

## 手动测试清单

部署完成后,做以下验证:

- [ ] 私聊机器人:发一条带 `/dxf` 和清晰 logo 图的消息 → 收到清理后图 + 预览图 + DXF
- [ ] 群聊里:同样的消息 → 收到同样结果
- [ ] 发 `/dxf` 不带图 → 机器人忽略(没反应)
- [ ] 发一张损坏的图片 → 机器人回复错误信息
- [ ] 两个人同时各发一张图 → 都正常完成
- [ ] `docker compose restart bot` → 机器人自动重连飞书,不需要人工介入

## 故障排查

| 现象 | 检查项 |
|------|--------|
| 容器一直重启 | `docker compose logs bot` 看 WS 连接错误,大概率是 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 错了 |
| 机器人收到消息但不回复"正在处理" | 检查飞书后台是否开通了 `im:message:receive_as_bot` 权限 |
| 豆包标准化失败 | 确认 `ARK_API_KEY` 有效,且账户开通了 Seedream 模型 |
| `HEALTHCHECK` 显示 unhealthy | `curl http://localhost:8080/healthz` 手动测,看进程是否在跑 |
| 转换出来的 DXF 是空的(0 个轮廓) | 原图对比度太低;先用 AI 标准化提亮后再试,或调整 `image_to_dxf.convert` 的 `--blur` 等参数 |

## 配置项说明

| 环境变量 | 必填 | 默认值 | 说明 |
|----------|------|--------|------|
| `FEISHU_APP_ID` | 是 | — | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 是 | — | 飞书应用 App Secret |
| `ARK_API_KEY` | 是 | — | 火山引擎 Ark API Key |
| `ARK_MODEL` | 否 | `doubao-seedream-4-0-250828` | 豆包模型名 |
| `LOG_LEVEL` | 否 | `INFO` | Python logging 级别 |
| `HEALTH_PORT` | 否 | `8080` | /healthz 端口(也是容器对外暴露的端口) |
| `WORK_DIR` | 否 | `/tmp/laser-bot` | 每次请求的临时工作目录根 |
| `CONVERT_TIMEOUT_S` | 否 | `60` | 单次 DXF 转换超时 |
| `MAX_WORKERS` | 否 | `3` | 并发处理的线程池大小 |

## 开发提示

- TDD:每个 leaf 模块都对应一个 `tests/test_*.py`,先写测试再写实现
- 调试时建议开 `LOG_LEVEL=DEBUG` 看到 lark SDK 的详细日志
- 改完代码想本地试:重启 `python -m app.main`,飞书那边可能要 5-10 秒才会重连

## 许可

MIT
