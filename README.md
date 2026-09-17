# RH Studio

把 RunningHub AI 应用收进自己的后台：输入 `webappId` 或应用链接，自动拉取 `nodeInfoList`，按 `fieldType` 生成表单，再提交运行、轮询产物。

不需要为每个应用手写适配器。应用作者改了工作流，点一次「刷新 schema」即可。

## 它参考了什么

- 官方动态表单示例：`GET /api/webapp/apiCallDemo` → 按 `fieldType` 渲染 → `POST /task/openapi/ai-app/run`
- [rainhon/runninghub-batch-api](https://github.com/rainhon/runninghub-batch-api)：FastAPI + SQLite、上传去重、任务轮询
- [HM-RunningHub/RH_CLI](https://github.com/HM-RunningHub/RH_CLI)：`rh app info / run`、从 URL 解析 webappId、提交时只带 `nodeId/fieldName/fieldValue`

RH Studio 比这些项目多做了一层**工具目录**：把 schema 存下来，支持显示名、分类、字段别名、隐藏 seed、手动刷新。

## 启动

```bat
cd rh-studio
python -m pip install -r requirements.txt
copy .env.example .env
python app.py
```

或双击 `start.bat`。浏览器打开 http://127.0.0.1:7788

1. 在「设置」粘贴 RunningHub API Key
2. 在「工具库」粘贴应用 ID，例如 `1937084629516193794`
   也可贴完整链接：`https://www.runninghub.cn/ai-detail/1937084629516193794`
3. 打开「运行」，上传文件 / 改提示词，提交
4. 「任务」页查看产物

没有 Key 时，可以先点「导入官方示例」，用 Flux Kontext 单图模式把界面跑通。真正提交任务仍需要 Key。

## 核心流程

1. 解析 webappId
2. 调用 `GET https://www.runninghub.cn/api/webapp/apiCallDemo?apiKey=...&webappId=...`
3. 把 `nodeInfoList` 写入 SQLite（`tools` + `tool_fields`）
4. 前端按 `STRING/LIST/INT/IMAGE...` 渲染控件
5. 图片/音视频先走 `POST /task/openapi/upload`，把返回的 `fileName` 填进 `fieldValue`
6. 提交 `POST /task/openapi/ai-app/run`
7. 后台线程轮询 `POST /task/openapi/outputs`
   - `0` 成功
   - `804` 运行中
   - `813` 排队
   - `805` 失败

## 注意

- 如果 `nodeInfoList` 为空，通常是这个应用还没在网页端成功跑过一次
- 文件字段必须先上传，不能直接塞本地路径
- 消费级 Key 和企业 Key 权限不同
- schema 会随作者改工作流变化，导入后请适时刷新
- 本项目是本机后台，不是会员/商城 SaaS

## 下一步可以加

- 批量队列和失败重试（参考 runninghub-batch-api）
- 应用市场浏览（RH_CLI 的 `rh app list`）
- 余额/算力展示
- webhook 回调
