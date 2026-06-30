/**
 * OSS 上传服务 —— presigned-upload 直传流程。
 *
 * 流程：
 *   1. POST /api/v1/oss/presign-upload  → 申请上传许可
 *      返回 { upload_url, public_url, file_id, object_name, expires_at }
 *   2. PUT upload_url + 文件字节        → 直传到 storage backend
 *      LocalStorage 模式 → 我们的 /api/v1/oss/direct-upload/{file_id}
 *      OSS 模式         → 阿里云 OSS 签名 URL
 *   3. 拿 public_url 给业务（设计审查 agent 等）
 *      public_url 是绝对 URL（含 scheme + host），视觉模型可直接 fetch
 */
import type { OSSUploadResult, OSSPresignRequest, OSSPresignResponse } from '@/types/oss';
import { apiRequest } from '@/api/apiClient';

async function putBytes(
  url: string,
  file: File,
  objectName: string,
  nonce: string,
  onProgress?: (sent: number, total: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  // 使用 XHR 以便支持进度回调（fetch 不支持）
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url, true);
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    // 防重放：必须把 nonce 放在 X-Nonce header（一次性消费）
    xhr.setRequestHeader('X-Nonce', nonce);
    // 必须把 presign 阶段生成的目标 object_name 回传给后端，
    // 否则后端 [oss_direct_upload] 会兜底写到 local://default/{file_id}{ext}，
    // 与 session prd_path 期望的 local://{business_bucket}/... 错位
    xhr.setRequestHeader('X-OSS-Object-Name', objectName);
    if (xhr.upload && onProgress) {
      xhr.upload.addEventListener('progress', (ev) => {
        if (ev.lengthComputable) onProgress(ev.loaded, ev.total);
      });
    }
    // 外部 signal 取消 → 中止 XHR
    if (signal) {
      if (signal.aborted) {
        xhr.abort();
        reject(new DOMException('Aborted', 'AbortError'));
        return;
      }
      signal.addEventListener('abort', () => {
        xhr.abort();
        reject(new DOMException('Aborted', 'AbortError'));
      });
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`PUT ${url} failed: ${xhr.status} ${xhr.responseText?.slice(0, 200)}`));
    };
    xhr.onerror = () => reject(new Error(`PUT ${url} network error`));
    xhr.send(file);
  });
}

/**
 * upload() 的选项对象。
 */
export interface UploadOptions {
  /** 业务分类（如 'design-review-prd' / 'design-review-image'） */
  bucket?: string;
  /** 取消信号（同时作用于 presign 请求与 PUT 直传） */
  signal?: AbortSignal;
  /** 进度回调（{ ratio, loaded, total }）—— 仅 LocalStorage 模式有效 */
  onProgress?: (progress: { ratio: number; loaded: number; total: number }) => void;
}

/**
 * 通过 presign-upload 流程上传文件。
 *
 * @param file    File 对象（必须真实存在）
 * @param options 业务选项 { bucket, signal, onProgress }
 * @returns OSSUploadResult —— **url 字段是绝对 URL**，可直接做 image_url
 */
export async function upload(
  file: File,
  options: UploadOptions = {},
): Promise<OSSUploadResult> {
  const {
    bucket = 'default',
    signal,
    onProgress,
  } = options;

  // 1) 申请上传许可（支持外部 signal 取消）
  const presignReq: OSSPresignRequest = {
    bucket,
    filename: file.name || 'file.bin',
    content_type: file.type || 'application/octet-stream',
    ttl_seconds: 3600,
  };
  const presign = await apiRequest<OSSPresignResponse>(
    '/api/v1/oss/presign-upload',
    { method: 'POST', body: presignReq, signal },
  );

  // 2) PUT 直传（带 X-Nonce 防重放 + X-OSS-Object-Name 回传目标路径）
  // 把 XHR 进度归一成 {ratio, loaded, total}，与 onProgress 契约对齐
  await putBytes(
    presign.upload_url,
    file,
    presign.object_name,
    presign.nonce,
    (loaded, total) => {
      onProgress?.({
        ratio: total > 0 ? loaded / total : 0,
        loaded,
        total,
      });
    },
    signal,
  );

  // 3) 返回业务结果
  return {
    object_name: presign.object_name,
    url: presign.public_url, // ← 绝对 URL，业务侧可直接 fetch
    file_id: presign.file_id,
    filename: file.name,
    file_type: bucket,       // 业务侧按 bucket 自解释类型
    file_size: file.size,
    storage_backend: presign.storage_backend,
  };
}

/**
 * 申请 upload_url（供前端分块上传 / 自定义直传使用）。
 *
 * 注意：拿到 upload_url 后不要忘记 PUT 文件字节，public_url 才会真可访问。
 */
export async function presignUpload(req: OSSPresignRequest): Promise<OSSPresignResponse> {
  return apiRequest<OSSPresignResponse>('/api/v1/oss/presign-upload', {
    method: 'POST',
    body: req,
  });
}

export const ossService = { upload, presignUpload };
export default ossService;