/**
 * OSS presign-upload 流程的类型定义。
 */

/** 申请上传许可的入参。 */
export interface OSSPresignRequest {
  /** 业务分类（design-review-prd / design-review-image / ...） */
  bucket: string;
  /** 原始文件名（含扩展名） */
  filename: string;
  /** MIME（默认从 filename 推断） */
  content_type?: string;
  /** upload_url / public_url 有效期（秒，默认 3600，min 60，max 7 天） */
  ttl_seconds?: number;
}

/** 申请上传许可的返回。 */
export interface OSSPresignResponse {
  /** 后端内部文件 ID */
  file_id: string;
  /** 对象名（local://bucket/file-xxx 或 bucket/file-xxx） */
  object_name: string;
  /** PUT 直传目标（绝对 URL） */
  upload_url: string;
  upload_method: 'PUT';
  /** 可被 fetch 拿到字节流的绝对 URL（视觉模型用） */
  public_url: string;
  /** ISO 8601 */
  expires_at: string;
  /** 'local' / 'oss' / 's3' */
  storage_backend: string;
  bucket: string;
  /** 防重放一次性令牌（32 字符 hex UUID v4）。
   *  客户端 PUT 直传时必须放在 X-Nonce header 里。
   *  服务端会原子消费（一次有效）。*/
  nonce: string;
}

/** upload() 函数的返回（封装业务侧需要的字段）。 */
export interface OSSUploadResult {
  object_name: string;
  /** 绝对 URL（业务侧可直接当 image_url 用） */
  url: string;
  file_id: string;
  filename: string;
  /** 业务侧类型（与 bucket 对齐） */
  file_type: string;
  file_size: number;
  storage_backend: string;
}