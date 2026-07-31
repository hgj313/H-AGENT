# 保险单识别系统 API 接口文档

> 版本：1.0.0  
> 更新日期：2026-07-31  
> Base URL：`http://<服务器IP>:8765`

---

## 一、概述

### 服务架构

| 项目 | 说明 |
|------|------|
| Web 框架 | FastAPI (ASGI) |
| 运行容器 | uvicorn |
| 监听地址 | `0.0.0.0:8765` |
| 请求限制 | 单进程，建议并发 ≤ 5 |
| 认证方式 | 无（内网部署，建议通过网关鉴权） |
| 文件格式 | 仅支持 `.pdf` |

### 核心流程

```
客户端上传 PDF → 服务端解析 → 提取被保人员 → 返回 JSON
                                                    ↓
                                        客户端调下载接口 → CSV / Excel
```

处理逻辑：
1. 上传的 PDF 先按**保单/批单**类型排序（保单优先，确保批单能关联主保单）
2. 每个 PDF 走 LangGraph 管道：解析 → 元数据提取 → 人员提取 → 身份证校验/补全 → 批单关联主保单
3. 结果缓存在服务端内存，供后续下载接口使用

---

## 二、接口列表

| # | 方法 | 路径 | 说明 |
|---|------|------|------|
| 1 | GET | `/api/health` | 健康检查 |
| 2 | POST | `/api/upload` | 上传 PDF 并提取人员信息（核心接口） |
| 3 | GET | `/api/download/csv` | 下载 CSV 表格 |
| 4 | GET | `/api/download/xlsx` | 下载 Excel 表格 |
| 5 | GET | `/api/policy-library` | 查询保单文件库 |

---

## 三、接口详情

### 1. 健康检查

```
GET /api/health
```

检测服务是否在线及 LLM 可用性。

**请求参数：** 无

**响应示例：**

```json
{
  "status": "ok",
  "llm_available": true
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 固定 `"ok"` |
| llm_available | boolean | LLM 客户端是否可用（影响扫描件 OCR） |

---

### 2. 上传 PDF 并提取人员信息（核心接口）

```
POST /api/upload
Content-Type: multipart/form-data
```

上传一个或多个 PDF 保单/批单文件，系统自动解析并返回被保人员清单。

**请求参数：**

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| files | formData | File[] | 是 | PDF 文件，字段名固定为 `files`，可传多个 |

**文件名约定（推荐）：**

文件名影响保单/批单类型识别和保单库关联，推荐格式：

```
保单_<公司名>_<保单号>.pdf          ← 主保单
批单_<公司名>_<保单号>.pdf          ← 批单
电子保单+<公司名>+<保单号>.pdf       ← 也支持
替换<N>人保单·<公司简称><日期>.pdf   ← 粤灿批单格式也支持
```

**响应示例（成功）：**

```json
{
  "success": true,
  "total_files": 2,
  "total_persons": 52,
  "total_add": 48,
  "total_remove": 4,
  "results": [
    {
      "file_name": "电子保单+广州市粤灿建设工程有限公司+X44061701260000083506.pdf",
      "insurance_company": "华农财产保险股份有限公司",
      "policy_number": "X44061701260000083506",
      "overall_start_date": "2026-03-20",
      "overall_end_date": "2026-09-19",
      "persons_count": 44,
      "add_count": 44,
      "remove_count": 0,
      "persons": [
        {
          "name": "张三",
          "id_number": "452725196702260048",
          "id_type": "身份证",
          "birth_date": "1967-02-26",
          "company": "广州市粤灿建设工程有限公司",
          "modification_type": "增保",
          "start_date": "2026-03-20",
          "end_date": "2026-09-19",
          "job_title": "钢筋工",
          "confidence": 0.85
        }
      ]
    },
    {
      "file_name": "替换4人保单·粤灿0612.pdf",
      "insurance_company": "华农财产保险股份有限公司",
      "policy_number": "X44061701260000083506",
      "overall_start_date": "2026-03-20",
      "overall_end_date": "2026-09-19",
      "persons_count": 8,
      "add_count": 4,
      "remove_count": 4,
      "persons": [
        {
          "name": "李四",
          "id_number": "440106199003150012",
          "id_type": "身份证",
          "birth_date": "1990-03-15",
          "company": "广州市粤灿建设工程有限公司",
          "modification_type": "增保",
          "start_date": "2026-06-13",
          "end_date": "2026-09-19",
          "job_title": "",
          "confidence": 0.9
        },
        {
          "name": "王五",
          "id_number": "440106198812200034",
          "id_type": "身份证",
          "birth_date": "1988-12-20",
          "company": "广州市粤灿建设工程有限公司",
          "modification_type": "减保",
          "start_date": "2026-06-13",
          "end_date": "2026-09-19",
          "job_title": "",
          "confidence": 0.9
        }
      ]
    }
  ]
}
```

**响应字段说明：**

顶层字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | boolean | 是否全部处理成功 |
| total_files | int | 处理的文件数 |
| total_persons | int | 提取的总人数 |
| total_add | int | 增保总人数 |
| total_remove | int | 减保总人数 |
| results | array | 每个文件的结果列表 |

results[] 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| file_name | string | 文件名 |
| insurance_company | string | 保险公司名称 |
| policy_number | string | 保单号 |
| overall_start_date | string | 保险期间起（YYYY-MM-DD） |
| overall_end_date | string | 保险期间止（YYYY-MM-DD） |
| persons_count | int | 该文件提取的人数 |
| add_count | int | 增保人数 |
| remove_count | int | 减保人数 |
| persons | array | 人员明细列表 |
| error | string | 仅处理失败时存在，描述错误原因 |

persons[] 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| name | string | 姓名 |
| id_number | string | 身份证号码（脱敏的会自动补全） |
| id_type | string | 证件类型，固定 `"身份证"` |
| birth_date | string | 出生日期（YYYY-MM-DD），从身份证号提取 |
| company | string | 所属公司/用工单位 |
| modification_type | string | 批改类型：`"增保"` 或 `"减保"` |
| start_date | string | 该人员保险起始时间 |
| end_date | string | 该人员保险起止时间 |
| job_title | string | 岗位名称/工种 |
| confidence | float | 提取置信度 0-1 |

**响应示例（部分文件失败）：**

```json
{
  "success": true,
  "total_files": 2,
  "total_persons": 3,
  "total_add": 3,
  "total_remove": 0,
  "results": [
    {
      "file_name": "保单_重庆森得尔劳务有限公司_8116013100260068880000(2).pdf",
      "insurance_company": "利宝保险有限公司",
      "policy_number": "8116013100260068880000",
      "overall_start_date": "2026-06-09",
      "overall_end_date": "2026-07-08",
      "persons_count": 3,
      "add_count": 3,
      "remove_count": 0,
      "persons": [...]
    },
    {
      "file_name": "损坏文件.pdf",
      "error": "PDF解析失败: ..."
    }
  ]
}
```

**错误响应：**

| HTTP 状态码 | 说明 |
|-------------|------|
| 400 | 未上传文件 / 未找到 PDF 文件 |
| 422 | 请求格式错误 |
| 500 | 服务端内部错误 |

---

### 3. 下载 CSV 表格

```
GET /api/download/csv
```

将最近一次 `/api/upload` 的结果导出为 CSV 表格（UTF-8 BOM 编码，Excel 可直接打开）。

**请求参数：** 无

**前置条件：** 必须先调用过 `/api/upload`，否则返回 404。

**响应：**

| 项目 | 说明 |
|------|------|
| Content-Type | `text/csv` |
| Content-Disposition | `attachment; filename*=UTF-8''被保人员清单_YYYYMMDD_HHMMSS.csv` |
| 编码 | UTF-8 with BOM |

**CSV 列顺序：**

```
姓名, 证件号码, 证件类型, 出生日期, 所属公司, 批改类型, 起始时间, 起止时间, 岗位名称, 保险公司, 保单号, 来源文件
```

**错误响应：**

| HTTP 状态码 | 说明 |
|-------------|------|
| 404 | 无提取结果，请先上传文件 |

---

### 4. 下载 Excel 表格

```
GET /api/download/xlsx
```

将最近一次 `/api/upload` 的结果导出为 Excel 表格（.xlsx），含样式：表头着色、增保浅红、减保浅蓝、冻结首行、自动列宽。

**请求参数：** 无

**前置条件：** 必须先调用过 `/api/upload`，否则返回 404。

**响应：**

| 项目 | 说明 |
|------|------|
| Content-Type | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| Content-Disposition | `attachment; filename*=UTF-8''被保人员清单_YYYYMMDD_HHMMSS.xlsx` |

**Sheet 名称：** `被保人员清单`

**列顺序：** 与 CSV 一致（12 列）。

---

### 5. 查询保单文件库

```
GET /api/policy-library
```

返回服务端保单库中已注册的所有保单记录。每次上传成功的保单会自动注册到库中，批单处理时会通过保单号或公司名匹配主保单补全起止时间。

**请求参数：** 无

**响应示例：**

```json
{
  "records": [
    {
      "file_name": "电子保单+广州市粤灿建设工程有限公司+X44061701260000083506.pdf",
      "policy_type": "保单",
      "policy_number": "X44061701260000083506",
      "company": "广州市粤灿建设工程有限公司",
      "insurance_company": "华农财产保险股份有限公司",
      "start_date": "2026-03-20",
      "end_date": "2026-09-19",
      "persons_count": 44
    },
    {
      "file_name": "保单_重庆森得尔劳务有限公司_8116013100260068880000(2).pdf",
      "policy_type": "保单",
      "policy_number": "8116013100260068880000",
      "company": "重庆森得尔劳务有限公司",
      "insurance_company": "利宝保险有限公司",
      "start_date": "2026-06-09",
      "end_date": "2026-07-08",
      "persons_count": 3
    }
  ],
  "total": 2
}
```

**records[] 字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| file_name | string | 文件名 |
| policy_type | string | `"保单"` 或 `"批单"` |
| policy_number | string | 保单号 |
| company | string | 投保公司名 |
| insurance_company | string | 保险公司名 |
| start_date | string | 保险起始日期 |
| end_date | string | 保险止期 |
| persons_count | int | 人数 |

---

## 四、集成示例

### curl

```bash
# 上传单个文件
curl -X POST http://localhost:8765/api/upload \
  -F "files=@保单_重庆森得尔劳务有限公司_8116013100260068880000.pdf"

# 上传多个文件（保单+批单）
curl -X POST http://localhost:8765/api/upload \
  -F "files=@电子保单+粤灿+X44061701260000083506.pdf" \
  -F "files=@替换4人保单·粤灿0612.pdf"

# 下载 CSV
curl -o 被保人员.csv http://localhost:8765/api/download/csv

# 下载 Excel
curl -o 被保人员.xlsx http://localhost:8765/api/download/xlsx
```

### Python (requests)

```python
import requests

BASE_URL = "http://localhost:8765"

# 上传 PDF
with open("保单_重庆森得尔.pdf", "rb") as f:
    resp = requests.post(
        f"{BASE_URL}/api/upload",
        files=[("files", ("保单_重庆森得尔.pdf", f, "application/pdf"))]
    )

data = resp.json()
print(f"提取 {data['total_persons']} 人 (增{data['total_add']}/减{data['total_remove']})")

for result in data["results"]:
    if result.get("error"):
        print(f"  错误: {result['file_name']}: {result['error']}")
        continue
    for person in result["persons"]:
        print(f"  {person['name']} | {person['id_number']} | {person['modification_type']}")

# 下载 Excel
excel_resp = requests.get(f"{BASE_URL}/api/download/xlsx")
with open("被保人员清单.xlsx", "wb") as f:
    f.write(excel_resp.content)
```

### JavaScript (fetch)

```javascript
const BASE_URL = "http://localhost:8765";

// 上传 PDF
const formData = new FormData();
formData.append("files", fileInput.files[0]);
formData.append("files", fileInput.files[1]);

const resp = await fetch(`${BASE_URL}/api/upload`, {
    method: "POST",
    body: formData,
});

const data = await resp.json();
console.log(`提取 ${data.total_persons} 人`);

// 下载 Excel — 用 window 直接跳转
window.location.href = `${BASE_URL}/api/download/xlsx`;
```

### Java (OkHttp)

```java
OkHttpClient client = new OkHttpClient.Builder()
    .connectTimeout(30, TimeUnit.SECONDS)
    .readTimeout(10, TimeUnit.MINUTES)  // 大文件处理需要长超时
    .build();

MultipartBody.Builder multipartBuilder = new MultipartBody.Builder()
    .setType(MultipartBody.FORM);

for (File pdfFile : pdfFiles) {
    multipartBuilder.addFormDataPart(
        "files",
        pdfFile.getName(),
        RequestBody.create(pdfFile, MediaType.parse("application/pdf"))
    );
}

Request request = new Request.Builder()
    .url("http://localhost:8765/api/upload")
    .post(multipartBuilder.build())
    .build();

try (Response response = client.newCall(request).execute()) {
    String json = response.body().string();
    System.out.println("结果: " + json);
}
```

---

## 五、注意事项

### 超时设置

PDF 处理耗时取决于文件大小和页数，建议客户端超时设置为 **10 分钟**：

| 文件类型 | 预估耗时 |
|---------|---------|
| 文字层保单（3-5页） | 3-10 秒 |
| 文字层保单（40+页） | 15-30 秒 |
| 扫描件保单（需 OCR） | 30-120 秒/页 |

### 并发限制

当前为单进程 (`workers=1`)，同时只处理一个上传请求。如果并发上传，请求会排队。建议公司系统接入时：

- 前端串行上传，一次传一批
- 或将 `workers` 改为 2-4（需确认内存够用）

### 数据生命周期

- 上传结果缓存在**内存**中，服务重启后丢失
- 下载接口返回的是**最近一次**上传的结果
- 保单库持久化在 `policy_library/index.json`，重启不丢失
- 上传的 PDF 临时文件存在系统 temp 目录，处理完不主动删除

### 批单关联主保单

- 同一批上传中，保单会先于批单处理
- 批单通过保单号精确匹配主保单，匹配失败则按公司名模糊匹配
- 匹配成功后，批单人员的 `end_date` 会补全为主保单的 `overall_end_date`
- 如需跨批次关联，确保主保单已上传过（已注册到保单库）

### 身份证号处理

- PDF 中脱敏的身份证号（如 `342225********6613`）会自动用出生日期补全
- 补全逻辑：用 `birth_date` 填充第 7-14 位 + 重新计算第 18 位校验码
- 返回的 `id_number` 是补全后的完整号码

---

## 六、错误码汇总

| HTTP 状态码 | 场景 | 说明 |
|-------------|------|------|
| 200 | 成功 | 正常返回 |
| 400 | 请求错误 | 未上传文件 / 未找到 PDF |
| 404 | 无数据 | 下载接口未找到上次提取结果 |
| 422 | 参数错误 | 请求格式不符合 FastAPI 校验规则 |
| 500 | 服务端错误 | PDF 解析异常 / Agent 执行异常 |

服务端错误时，响应体中 `results[].error` 字段包含具体错误信息。
