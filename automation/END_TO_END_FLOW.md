# ZJGJ 端到端自动化流程

`run_end_to_end_flow.py` 将 **发布项目公告** 到 **发布中标公示** 的完整链路编排为一条可复用命令，复用 `automation/others` 核心库（只读，不修改）。

## 流程阶段

| 阶段 | 配置开关 | 说明 |
|------|----------|------|
| **A 标前** | `phases.publish` / `phases.bidders` | 扫描文件夹、OCR 提取 PDF、发布公告、投标报名/缴费/递交 |
| **B 开标** | `phases.experts` / `phases.decrypt` | 专家邀请/确认/签到、组长选举 (leaderVote)、全部投标人解密 |
| **C 评标** | `phases.review` / `phases.report` | 形式/资格/响应性评审 + 商务/技术/报价打分（`score_strategy=varied`）、saveReport、专家 reportSign、pushTenderReport |
| **D 公示** | `phases.notice` | addNotice 发布中标公示（取 getCandidate 第一名） |

## 环境准备

```powershell
# 设置 admin 账号（token 刷新、模拟缴费）
$env:ZJGJ_ADMIN_NAME = "adminz"
$env:ZJGJ_ADMIN_PASSWORD = "your-password"

cd d:\Document\LAB\AI\bidding-test-doc\bidding-test-doc\automation
```

核心库路径（脚本内已配置）：

```
d:\Document\others\LAB\AI\bidding-test-doc\bidding-test-doc\automation
```

## 快速开始

### 1. 复制并编辑配置

```powershell
copy config.end_to_end.example.json config.my_run.json
# 填入 tokens、materials_folder、人员 uid
```

### 2. 完整新跑（从文件夹到中标公示）

```powershell
python run_end_to_end_flow.py `
  --config config.my_run.json `
  --folder "d:\文件\客户项目文件\项目集\I\4"
```

### 3. 仅预览（不调 API）

```powershell
python run_end_to_end_flow.py --config config.my_run.json --folder "d:\...\I\4" --dry-run
```

### 4. 续跑已有项目

```powershell
# 从解密阶段继续
python run_end_to_end_flow.py --config config.my_run.json --project-id 2104 --stop-after decrypt

# 仅补评审 + 报告 + 公示
python run_end_to_end_flow.py --config config.my_run.json --project-id 2691 --section-id 2488
```

## CLI 参数

| 参数 | 说明 |
|------|------|
| `--config` | JSON 配置文件（默认 `config.end_to_end.example.json`） |
| `--folder` | 项目材料目录，覆盖 `materials_folder` |
| `--project-id` | 续跑已有项目（自动跳过发布公告） |
| `--section-id` | 标段 ID，默认取第一个标段 |
| `--stop-after` | 完成后停止：`decrypt` \| `review` \| `report` \| `notice` |
| `--dry-run` | 扫描 + 配置预览，不写 API |
| `--decrypt-password` | 解密密码，默认 `submit.password` 或 `123456` |
| `--no-token-refresh` | 跳过 admin impersonate 刷新 token |
| `--report` / `--log` | 自定义报告/日志路径 |

## 输出

每次运行生成：

- `end_to_end_flow_report_YYYYMMDD_HHMMSS.json` — 各阶段结果汇总
- 同名 `.log` 日志文件

## 配置要点

### phases 开关

```json
"phases": {
  "publish": true,
  "bidders": true,
  "experts": true,
  "decrypt": true,
  "review": true,
  "report": true,
  "notice": true
}
```

设为 `false` 可跳过对应阶段（续跑时常用）。

### 大 PDF 上传

在 `extraction.upload_file_overrides_by_pdf` 中指定压缩后的轻量 PDF，与 I/4 项目做法一致。

### token 刷新

`token_refresh.enabled: true` 时，失效 token 会通过 admin impersonate 自动刷新（需 `ZJGJ_ADMIN_PASSWORD`）。

## 依赖的核心模块（只读）

- `zjgj_client.py` — API 客户端、评审步骤常量
- `run_full_automation.py` — 扫描、token 刷新、build_run_config
- `run_three_stage_flow.py` — 发布/投标/专家流程
- `run_bid_opening.py` — 开标、签到、解密
- `run_project_folder.py` / `bid_pdf_extract.py` — 文件夹扫描与 PDF 提取

**本目录下现有脚本均未修改**，仅新增上述三个文件。
