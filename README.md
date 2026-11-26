# 数据安全计算与隐私保护平台

面向数据脱敏、差分隐私、安全聚合与访问审计的数据安全计算与隐私保护平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 脱敏规则 | `mask_rule` | 脱敏规则 | 规则编号、目标字段、脱敏算法 |
| 隐私预算 | `privacy_budget` | 隐私预算 | 预算编号、数据集名称、总预算Epsilon |
| 噪声引擎 | `noise_engine` | 噪声配置 | 配置编号、噪声机制、Epsilon值 |
| 安全聚合 | `secure_agg` | 聚合任务 | 任务编号、数据源列表、聚合函数 |
| 访问审计 | `access_audit` | 审计记录 | 记录编号、访问主体、目标资源 |
| 授权审批 | `grant_approval` | 授权申请 | 申请编号、申请人、目标数据 |
| 分级分类 | `classify_tag` | 分级标签 | 标签编号、数据资源、安全等级 |
| 联邦训练 | `federated_train` | 训练任务 | 任务编号、参与节点、模型类型 |
| 梯度加密 | `gradient_encrypt` | 加密配置 | 配置编号、加密方案、密钥长度 |
| 假名化 | `pseudonym` | 假名映射 | 映射编号、原始标识、假名标识 |
| K匿名检查 | `k_anonymity` | 匿名检查 | 检查编号、数据集名称、准标识符列 |
| 差分查询 | `differential_sql` | 查询记录 | 查询编号、查询语句、查询用户 |
| 密文索引 | `encrypt_index` | 索引条目 | 条目编号、加密域、索引类型 |
| 数据水印 | `watermark` | 水印记录 | 水印编号、目标数据集、水印算法 |
| 同意登记 | `consent_registry` | 同意记录 | 记录编号、数据主体、处理目的 |
| 风险扫描 | `risk_scan` | 扫描任务 | 任务编号、扫描范围、扫描规则 |
| 策略下发 | `deploy_policy` | 策略分发 | 分发编号、策略内容、目标节点 |
| 异常检测 | `anomaly_detect` | 异常规则 | 规则编号、检测维度、检测算法 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 假名交付确认（pseudonym-delivery）

假名化模块支持映射轮换版本链（`版本链ID` + `映射代次`），并通过独立的
「假名交付确认」工作台把已核验样本批次核发为假名交付单：

- 交付确认时冻结映射快照（版本/代次/盐值），文件与交付单永远指向同一次生成；
  映射轮换后，已确认的在途文件任务仍按先前确认版本在后台完成，不混用两版。
- 已失效、已轮换且未经确认的映射，以及未核验批次，在核发阶段直接拦截，
  不能生成新的交付文件；历史已交付文件长期保留、可下载、可追溯。
- 仅打开确认页未确认的请求为「待确认」草稿；轮换后草稿标注「需重新提交」，
  确认会被拦截，重新提交刷新到当前有效映射后才可确认。
- 文件生成时自动写入带交付指纹的水印记录，水印详情可核对关联交付单、
  样本批次与冻结映射版本。

后端接口前缀 `/api/pseudonym-delivery`：

| 接口 | 说明 |
| --- | --- |
| `GET /batches` | 样本批次（前端只允许选已核验） |
| `GET /orders` / `GET /orders/{id}` | 交付请求列表/详情，带实时版本冲突标注 |
| `POST /prepare` | 打开确认页，生成待确认草稿，不产生文件 |
| `POST /confirm` | 按批次+映射核发已确认交付单并排队文件任务 |
| `POST /orders/{id}/confirm` | 确认草稿请求 |
| `POST /orders/{id}/resubmit` | 草稿按当前有效映射重新提交 |
| `POST /orders/{id}/generate` | 启动后台文件生成（冻结版本） |
| `GET /orders/{id}/download` | 下载已生成的假名交付文件 |
| `GET /watermark-traces` / `/{watermark_id}` | 水印溯源列表与详情 |

领域：数据工程
子方向：数据分析与数据应用
