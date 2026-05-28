# Chroma SQLite 数据库表结构文档

> 数据来源：`C:\HGJ-T\H-AGENT\persistence\data\chroma_db\chroma.sqlite3`
> 生成日期：2026/05/28

---

## 一、整体架构

Chroma 是一个向量数据库，采用多租户设计，数据层级关系如下：

```
tenants (租户)
  └── databases (租户内数据库)
        └── collections (向量集合)
              └── segments (数据分片)
                    └── embeddings (向量 + 元数据)
```

---

## 二、所有表及列说明

### 2.1 tenants — 租户隔离顶层

| 列 | 类型 | 主键 | 含义 |
|---|---|---|---|
| `id` | TEXT | ✅ | 租户唯一标识符 |

**当前数据：**
```
default_tenant
```

---

### 2.2 databases — 租户内的数据库实例

| 列 | 类型 | 主键 | 外键 | 含义 |
|---|---|---|---|---|
| `id` | TEXT | ✅ | — | 数据库全局唯一ID |
| `name` | TEXT NOT NULL | — | — | 数据库名称（租户内唯一） |
| `tenant_id` | TEXT NOT NULL | — | ✅ → tenants | 所属租户 |

**当前数据：**
```
00000000-0000-0000-0000-000000000000 | default_database | default_tenant
```

---

### 2.3 collections — 向量集合（等同于"表"的概念）

| 列 | 类型 | 主键 | 外键 | 含义 |
|---|---|---|---|---|
| `id` | TEXT | ✅ | — | 集合唯一ID（UUID） |
| `name` | TEXT NOT NULL | — | — | 集合名称（数据库内唯一） |
| `dimension` | INTEGER | — | — | 向量维度（如 1024） |
| `database_id` | TEXT NOT NULL | — | ✅ → databases | 所属数据库 |
| `config_json_str` | TEXT | — | — | 集合配置（索引类型、度量方式等）JSON 字符串 |
| `schema_str` | TEXT | — | — | 集合 schema 的 JSON 字符串 |

**当前数据：**
```
34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab | vectors | 1024 | 00000000-0000-0000-0000-000000000000 | {} | {...}
```

---

### 2.4 segments — 集合内的数据分片

| 列 | 类型 | 主键 | 外键 | 含义 |
|---|---|---|---|---|
| `id` | TEXT | ✅ | — | 分片唯一ID（UUID） |
| `type` | TEXT NOT NULL | — | — | 分片类型：`urn:chroma:segment/vector/hnsw-local-persisted`（向量）或 `urn:chroma:segment/metadata/sqlite`（元数据） |
| `scope` | TEXT NOT NULL | — | — | 作用域：`VECTOR` 或 `METADATA` |
| `collection` | TEXT | — | ✅ → collections | 所属集合 ID |

**当前数据：**
```
631da276-deb7-4f18-8dc5-0bb9379f123b | urn:chroma:segment/vector/hnsw-local-persisted | VECTOR | 34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab
649c3ec4-432d-4704-8b19-3e03647a080b | urn:chroma:segment/metadata/sqlite | METADATA | 34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab
```

---

### 2.5 embeddings — 实际向量数据

| 列 | 类型 | 主键 | 外键 | 含义 |
|---|---|---|---|---|
| `id` | INTEGER | ✅ | — | 自增主键 |
| `segment_id` | TEXT NOT NULL | — | ✅ → segments | 所属的分片（哪个 segment 存储这个向量） |
| `embedding_id` | TEXT NOT NULL | — | — | 向量的唯一标识（UUID） |
| `seq_id` | BLOB NOT NULL | — | — | 序列号（保证顺序） |
| `created_at` | TIMESTAMP NOT NULL | — | — | 创建时间 |

**当前数据示例：**
| id | segment_id | embedding_id | seq_id | created_at |
|---|---|---|---|---|
| 1 | `649c3ec4...` (METADATA segment) | `94b1eccce5f4a260` | 1 | 2026-05-28 02:33:32 |
| 2 | `649c3ec4...` | `42d710aff22e7bf6` | 2 | 2026-05-28 02:33:32 |
| 3 | `649c3ec4...` | `2829bb3c006132b3` | 3 | 2026-05-28 02:33:32 |
| 4 | `649c3ec4...` | `6046967694aaa1af` | 4 | 2026-05-28 02:33:32 |
| 5 | `649c3ec4...` | `9ca2ab778c3afe40` | 5 | 2026-05-28 02:33:32 |

---

### 2.6 embedding_metadata — 向量的键值元数据（标量类型）

| 列 | 类型 | 主键 | 外键 | 含义 |
|---|---|---|---|---|
| `id` | INTEGER | — | ✅ → embeddings | 关联的向量 ID |
| `key` | TEXT NOT NULL | ✅ | — | 元数据键名 |
| `string_value` | TEXT | — | — | 字符串值 |
| `int_value` | INTEGER | — | — | 整数值 |
| `float_value` | REAL | — | — | 浮点值 |
| `bool_value` | INTEGER | — | — | 布尔值（存为 0/1） |

**重要键名说明：**

| key | 含义 |
|---|---|
| `chroma:document` | 原始文档/文本内容 |
| `name` | 向量/文档的名称 |
| `start_index` | 文档切片起始位置 |
| `chunk_type` | 切片类型（如 `text`） |
| `shit` | 自定义测试字段（值为 `boolshit`） |

**数据示例：**
| id | key | string_value |
|---|---|---|
| 1 | `chroma:document` | `# 吉盛园林工程里程碑看板...`（长文档内容） |
| 1 | `name` | `测试` |
| 1 | `shit` | `boolshit` |
| 1 | `chunk_type` | `text` |
| 1 | `start_index` | `0` |
| 2 | `start_index` | `564` |

---

### 2.7 embedding_metadata_array — 数组类型元数据

| 列 | 类型 | 主键 | 外键 | 含义 |
|---|---|---|---|---|
| `id` | INTEGER NOT NULL | — | ✅ → embeddings | 关联的向量 ID |
| `key` | TEXT NOT NULL | ✅ | — | 元数据键名 |
| `string_value` | TEXT | — | — | 字符串值 |
| `int_value` | INTEGER | — | — | 整数值 |
| `float_value` | REAL | — | — | 浮点值 |
| `bool_value` | INTEGER | — | — | 布尔值 |

与 `embedding_metadata` 的区别：支持数组元素的 `$contains` 查询，每个数组元素独占一行。

---

### 2.8 max_seq_id — 每个 segment 的最大序列号

| 列 | 类型 | 主键 | 外键 | 含义 |
|---|---|---|---|---|
| `segment_id` | TEXT | ✅ | ✅ → segments | 分片 ID |
| `seq_id` | INTEGER | — | — | 该分片当前最大序列号 |

**当前数据：**
```
649c3ec4-432d-4704-8b19-3e03647a080b | 5
```
（说明该 METADATA 分片已有 5 条向量）

---

### 2.9 collection_metadata — 集合级元数据

| 列 | 类型 | 主键 | 外键 | 含义 |
|---|---|---|---|---|
| `collection_id` | TEXT | ✅ | ✅ → collections | 集合 ID |
| `key` | TEXT NOT NULL | ✅ | — | 元数据键名 |
| `str_value` | TEXT | — | — | 字符串值 |
| `int_value` | INTEGER | — | — | 整数值 |
| `float_value` | REAL | — | — | 浮点值 |
| `bool_value` | INTEGER | — | — | 布尔值 |

**当前数据：**
```
34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab | hnsw:space | cosine
```
（说明该集合使用余弦相似度作为向量距离度量）

---

### 2.10 segment_metadata — 分片级元数据

结构与 `collection_metadata` 相同，关联到 segments 表。当前无数据。

| 列 | 类型 | 主键 | 外键 | 含义 |
|---|---|---|---|---|
| `segment_id` | TEXT | ✅ | ✅ → segments | 分片 ID |
| `key` | TEXT NOT NULL | ✅ | — | 元数据键名 |
| `str_value` | TEXT | — | — | 字符串值 |
| `int_value` | INTEGER | — | — | 整数值 |
| `float_value` | REAL | — | — | 浮点值 |
| `bool_value` | INTEGER | — | — | 布尔值 |

---

### 2.11 embeddings_queue — 消息队列（待写入的向量操作）

| 列 | 类型 | 主键 | 含义 |
|---|---|---|---|
| `seq_id` | INTEGER | ✅ | 消息序列号（自增） |
| `created_at` | TIMESTAMP NOT NULL | — | 创建时间 |
| `operation` | INTEGER NOT NULL | — | 操作类型：`0`=添加（Add） |
| `topic` | TEXT NOT NULL | — | **集合标识符**（URI 格式） |
| `id` | TEXT NOT NULL | — | 向量 ID（UUID） |
| `vector` | BLOB | — | 向量数据（二进制，FLOAT32） |
| `encoding` | TEXT | — | 编码格式（如 `FLOAT32`） |
| `metadata` | TEXT | — | 元数据 JSON 字符串 |

**关于 `topic` 列的解释：**

`topic` 列是早期版本遗留的列（见 migrations 表中 v1-v2 的原始建表语句）。在多租户架构下，`topic` 的值格式为：
```
persistent://{tenant}/{database}/{collection_id}
```

例如：
```
persistent://default/default/34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab
           ↑       ↑       ↑
         租户    数据库   集合ID
```

**当前数据示例：**
| seq_id | operation | topic | id |
|---|---|---|---|
| 1 | 0 | `persistent://default/default/34fcc5d7...` | `94b1eccce5f4a260` |
| 2 | 0 | `persistent://default/default/34fcc5d7...` | `42d710aff22e7bf6` |
| 3 | 0 | `persistent://default/default/34fcc5d7...` | `2829bb3c006132b3` |
| 4 | 0 | `persistent://default/default/34fcc5d7...` | `6046967694aaa1af` |
| 5 | 0 | `persistent://default/default/34fcc5d7...` | `9ca2ab778c3afe40` |

（5 条 Add 操作，都指向同一个 collection）

---

### 2.12 embeddings_queue_config — 队列配置

| 列 | 类型 | 主键 | 含义 |
|---|---|---|---|
| `id` | INTEGER | ✅ | 配置 ID |
| `config_json_str` | TEXT | — | 配置 JSON 字符串 |

---

### 2.13 migrations — 数据库迁移历史

| 列 | 类型 | 主键 | 含义 |
|---|---|---|---|
| `dir` | TEXT | ✅ | 迁移目录（`sysdb` / `metadb` / `embeddings_queue`） |
| `version` | INTEGER | ✅ | 迁移版本号 |
| `filename` | TEXT NOT NULL | — | 迁移文件名 |
| `sql` | TEXT NOT NULL | — | 执行的 SQL 语句 |
| `hash` | TEXT NOT NULL | — | SQL 的哈希值（校验完整性） |

**迁移历史（按版本顺序）：**

| 版本 | 目录 | 文件 | 说明 |
|---|---|---|---|
| v1 | sysdb | `00001-collections.sqlite.sql` | 创建 collections 和 collection_metadata 表（当时有 `topic` 列） |
| v2 | sysdb | `00002-segments.sqlite.sql` | 创建 segments 和 segment_metadata 表 |
| v3 | sysdb | `00003-collection-dimension.sqlite.sql` | 给 collections 添加 `dimension` 列 |
| v4 | sysdb | `00004-tenants-databases.sqlite.sql` | 引入多租户架构，创建 tenants 和 databases 表，创建默认租户/数据库 |
| v5 | sysdb | `00005-remove-topic.sqlite.sql` | **移除** collections 和 segments 表中的 `topic` 列 |
| v6 | sysdb | `00006-collection-segment-metadata.sqlite.sql` | 给 collection_metadata 和 segment_metadata 添加 `bool_value` 列 |
| v7 | sysdb | `00007-collection-config.sqlite.sql` | 给 collections 添加 `config_json_str` 列 |
| v8 | sysdb | `00008-maintenance-log.sqlite.sql` | 创建 maintenance_log 表记录 vacuum 操作 |
| v9 | sysdb | `00009-segment-collection-not-null.sqlite.sql` | 将 segments.collection 改为非空约束 |
| v10 | sysdb | `00010-collection-schema.sqlite.sql` | 给 collections 添加 `schema_str` 列 |
| v1 | metadb | `00001-embedding-metadata.sqlite.sql` | 创建 embeddings、embedding_metadata、max_seq_id 表和 embedding_fulltext 虚拟表 |
| v2 | metadb | `00002-embedding-metadata.sqlite.sql` | 给 embedding_metadata 添加 `bool_value` 列 |
| v3 | metadb | `00003-full-text-tokenize.sqlite.sql` | 创建 embedding_fulltext_search 虚拟表（trigram 分词） |
| v4 | metadb | `00004-metadata-indices.sqlite.sql` | 给 embedding_metadata 添加 int/float/string 值的索引 |
| v5 | metadb | `00005-max-seq-id-int.sqlite.sql` | 将 max_seq_id.seq_id 从 BLOB 转换为 INTEGER |
| v6 | metadb | `00006-metadata-array-support.sqlite.sql` | 创建 embedding_metadata_array 表支持数组元数据 |
| v1 | embeddings_queue | `00001-embeddings.sqlite.sql` | 创建 embeddings_queue 表 |
| v2 | embeddings_queue | `00002-embeddings-queue-config.sqlite.sql` | 创建 embeddings_queue_config 表 |

---

### 2.14 acquire_write — 分布式写锁状态

| 列 | 类型 | 主键 | 含义 |
|---|---|---|---|
| `id` | INTEGER | ✅ | 锁记录 ID |
| `lock_status` | INTEGER NOT NULL | — | 锁状态：`1`=已锁定 |

**当前数据：**
```
1 | 1
```

---

### 2.15 maintenance_log — 数据库维护操作日志

| 列 | 类型 | 主键 | 含义 |
|---|---|---|---|
| `id` | INT | ✅ | 日志 ID |
| `timestamp` | INT NOT NULL | — | 时间戳（Unix epoch） |
| `operation` | TEXT NOT NULL | — | 操作类型（如 `vacuum`） |

---

### 2.16 embedding_fulltext_search — FTS5 虚拟表（全文检索）

这是一个虚拟表，由 FTS5 引擎管理，用于对 `embedding_metadata.string_value` 进行全文检索。

**分词方式：** `trigram`（支持模糊匹配）

**关联内部表：**

| 表名 | 用途 |
|---|---|
| `embedding_fulltext_search_data` | 存储 FTS5 索引数据块 |
| `embedding_fulltext_search_idx` | 存储 FTS5 索引术语 |
| `embedding_fulltext_search_content` | 存储 FTS5 内容 |
| `embedding_fulltext_search_docsize` | 存储文档大小 |
| `embedding_fulltext_search_config` | 存储 FTS5 配置 |

---

## 三、SQL 查询示例

### 3.1 基础查询

```sql
-- 查找所有租户
SELECT * FROM tenants;

-- 查找所有数据库
SELECT * FROM databases;

-- 查找所有集合（collections）
SELECT id, name, dimension FROM collections;

-- 查找某集合的所有 segment
SELECT id, type, scope FROM segments
WHERE collection = '34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab';
```

### 3.2 向量与元数据查询

```sql
-- 查找某集合的所有向量（通过 segment 关联）
SELECT e.id, e.embedding_id, e.seq_id, e.created_at
FROM embeddings e
WHERE e.segment_id IN (
    SELECT id FROM segments
    WHERE collection = '34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab'
);

-- 按 key 查找特定元数据（如查找 name="测试" 的所有向量）
SELECT e.id, e.embedding_id, em.string_value
FROM embeddings e
JOIN embedding_metadata em ON e.id = em.id
WHERE em.key = 'name' AND em.string_value = '测试';

-- 查找某个向量的所有元数据
SELECT key, string_value, int_value, float_value, bool_value
FROM embedding_metadata
WHERE id = 1;

-- 查找包含特定文档内容的向量
SELECT e.id, e.embedding_id, em.string_value
FROM embeddings e
JOIN embedding_metadata em ON e.id = em.id
WHERE em.key = 'chroma:document'
AND em.string_value LIKE '%里程碑%';
```

### 3.3 配置与元信息查询

```sql
-- 查找集合配置（度量空间）
SELECT key, str_value FROM collection_metadata
WHERE collection_id = '34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab';

-- 统计每个 segment 的向量数量
SELECT s.id, s.type, COUNT(e.id) as embedding_count
FROM segments s
LEFT JOIN embeddings e ON s.id = e.segment_id
WHERE s.collection = '34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab'
GROUP BY s.id;

-- 查找每个集合的向量总数
SELECT c.name, COUNT(e.id) as total_embeddings
FROM collections c
JOIN segments s ON c.id = s.collection
JOIN embeddings e ON s.id = e.segment_id
GROUP BY c.id;
```

### 3.4 全文搜索（FTS5）

```sql
-- 在文档内容中进行全文搜索
SELECT em.id, em.string_value
FROM embedding_fulltext_search
WHERE string_value MATCH '里程碑';

-- 搜索多个关键词
SELECT em.id, em.string_value
FROM embedding_fulltext_search
WHERE string_value MATCH '项目管理 OR 延期';

-- 搜索前缀匹配
SELECT em.id, em.string_value
FROM embedding_fulltext_search
WHERE string_value MATCH '"项目"*';
```

### 3.5 队列查询

```sql
-- 查找队列中所有待处理操作
SELECT seq_id, topic, id, operation, created_at
FROM embeddings_queue;

-- 查找队列中指向特定集合的所有待处理操作
SELECT * FROM embeddings_queue
WHERE topic = 'persistent://default/default/34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab';

-- 统计队列中各集合的待处理操作数量
SELECT topic, COUNT(*) as count
FROM embeddings_queue
GROUP BY topic;
```

### 3.6 系统信息查询

```sql
-- 查看数据库迁移历史
SELECT dir, version, filename, hash FROM migrations
ORDER BY dir, version;

-- 查看维护日志
SELECT * FROM maintenance_log;

-- 查看当前写锁状态
SELECT * FROM acquire_write;

-- 查看各 segment 的最大序列号
SELECT * FROM max_seq_id;
```

---

## 四、数据流向示意

```
用户添加向量
    │
    ▼
embeddings_queue (消息队列，等待处理)
    │  operation=0 表示 Add
    │  topic 指向目标 collection
    │
    ▼
处理后写入
    │
    ├──→ segments (type="urn:chroma:segment/metadata/sqlite")
    │         │
    │         ▼
    │    embeddings (向量数据)
    │         │
    │         ├──→ embedding_metadata (标量元数据)
    │         └──→ embedding_metadata_array (数组元数据)
    │
    └──→ segments (type="urn:chroma:segment/vector/hnsw-local-persisted")
              │
              ▼
         HNSW 索引文件（.bin）
```

---

## 五、关于 persistent:// URI 格式说明

`embeddings_queue.topic` 列中出现的 URI 格式为：

```
persistent://{tenant}/{database}/{collection_id}
```

示例：
```
persistent://default/default/34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab
```

对应关系：
- `tenant` = `default_tenant`（默认租户）
- `database` = `default_database`（默认数据库）
- `collection_id` = `34fcc5d7-1f4e-4f1d-82f8-0a81a15b26ab`（即名为 `vectors` 的集合，1024维）

---

## 六、索引说明

为提升查询性能，以下索引已创建：

| 索引名 | 表 | 列 | 条件 |
|---|---|---|---|
| `embedding_metadata_int_value` | `embedding_metadata` | `(key, int_value)` | `WHERE int_value IS NOT NULL` |
| `embedding_metadata_float_value` | `embedding_metadata` | `(key, float_value)` | `WHERE float_value IS NOT NULL` |
| `embedding_metadata_string_value` | `embedding_metadata` | `(key, string_value)` | `WHERE string_value IS NOT NULL` |
| `embedding_metadata_array_id_key` | `embedding_metadata_array` | `(id, key)` | — |
| `embedding_metadata_array_key_string` | `embedding_metadata_array` | `(key, string_value)` | `WHERE string_value IS NOT NULL` |
| `embedding_metadata_array_key_int` | `embedding_metadata_array` | `(key, int_value)` | `WHERE int_value IS NOT NULL` |
| `embedding_metadata_array_key_float` | `embedding_metadata_array` | `(key, float_value)` | `WHERE float_value IS NOT NULL` |

---

*文档结束*