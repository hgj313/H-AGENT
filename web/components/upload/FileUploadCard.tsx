"use client";

/**
 * FileUploadCard - 通用文件上传组件（OSS 直传）
 *
 * 职责：
 *  - 拖拽 / 点击选择文件
 *  - 单文件 / 多文件模式
 *  - XHR 实时进度
 *  - 失败重试 / 取消
 *  - 文件预览（图片缩略图 / 文档图标）
 *
 * 状态机：idle → uploading → done | error
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { Button } from "@/components/common/Button";
import { ossService, type OSSUploadResult } from "@/services/ossService";

export interface FileUploadCardProps {
  /** 受控值：当前已上传文件列表 */
  value: OSSUploadResult[];
  /** 值变化回调 */
  onChange: (next: OSSUploadResult[]) => void;
  /** 接受的文件扩展名（含点），如 [".pdf", ".md"]；空 = 全部 */
  accept?: string[];
  /** 接受的文件 MIME 模式，如 ["image/*"] */
  acceptMime?: string[];
  /** 多文件模式 */
  multiple?: boolean;
  /** 单文件最大字节数，默认 50MB */
  maxSize?: number;
  /** bucket 子目录（按业务隔离） */
  bucket?: string;
  /** 标题 / 描述 */
  title: string;
  description?: string;
  /** 拖拽区提示 */
  placeholder?: string;
  /** 禁用 */
  disabled?: boolean;
}

type UploadItemState = {
  id: string;
  file: File;
  result?: OSSUploadResult;
  progress: number; // 0..1
  status: "uploading" | "done" | "error";
  error?: string;
  /** 用于取消的 AbortController */
  controller?: AbortController;
};

const formatSize = (n: number) => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
};

const isAccepted = (file: File, accept?: string[], acceptMime?: string[]) => {
  if (accept && accept.length) {
    const lower = file.name.toLowerCase();
    if (!accept.some((ext) => lower.endsWith(ext.toLowerCase()))) return false;
  }
  if (acceptMime && acceptMime.length) {
    if (!acceptMime.some((m) => {
      if (m.endsWith("/*")) {
        return file.type.startsWith(m.slice(0, -1));
      }
      return file.type === m;
    })) return false;
  }
  return true;
};

export function FileUploadCard({
  value,
  onChange,
  accept,
  acceptMime,
  multiple = false,
  maxSize = 50 * 1024 * 1024,
  bucket = "default",
  title,
  description,
  placeholder = "拖拽文件到此处，或点击选择",
  disabled = false,
}: FileUploadCardProps) {
  const [items, setItems] = useState<UploadItemState[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const acceptAttr = useMemo(() => {
    const parts: string[] = [];
    if (accept) parts.push(...accept);
    if (acceptMime) parts.push(...acceptMime);
    return parts.join(",") || undefined;
  }, [accept, acceptMime]);

  const updateItem = useCallback(
    (id: string, patch: Partial<UploadItemState>) => {
      setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...patch } : it)));
    },
    [],
  );

  const handleFiles = useCallback(
    async (files: File[]) => {
      if (disabled) return;
      const valid = files.filter((f) => isAccepted(f, accept, acceptMime));
      const skipped = files.length - valid.length;
      const newItems: UploadItemState[] = valid.map((f) => ({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        file: f,
        progress: 0,
        status: "uploading" as const,
      }));
      if (skipped > 0) {
        // 静默跳过不可接受的（已通过 accept 输入过滤）
      }
      setItems((prev) => (multiple ? [...prev, ...newItems] : newItems));
      for (const it of newItems) {
        if (it.file.size > maxSize) {
          updateItem(it.id, {
            status: "error",
            error: `文件超过 ${formatSize(maxSize)}`,
          });
          continue;
        }
        const controller = new AbortController();
        updateItem(it.id, { controller });
        ossService
          .upload(it.file, {
            bucket,
            signal: controller.signal,
            onProgress: (p) => updateItem(it.id, { progress: p.ratio }),
          })
          .then((result) => {
            updateItem(it.id, { status: "done", result, progress: 1 });
            const next = multiple
              ? [...value, result]
              : [result];
            onChange(next);
          })
          .catch((err) => {
            if (err instanceof DOMException && err.name === "AbortError") {
              setItems((prev) => prev.filter((x) => x.id !== it.id));
              return;
            }
            updateItem(it.id, {
              status: "error",
              error: err?.message || "上传失败",
            });
          });
      }
    },
    [accept, acceptMime, bucket, disabled, maxSize, multiple, onChange, updateItem, value],
  );

  const retry = (id: string) => {
    const it = items.find((x) => x.id === id);
    if (!it) return;
    // 复用原 File 与已算过的 hash（同 hash → 后端命中，不真实上传）
    setItems((prev) =>
      prev.map((x) =>
        x.id === id
          ? { ...x, status: "uploading", progress: 0, error: undefined }
          : x,
      ),
    );
    void handleFiles([it.file]);
  };

  const remove = (id: string) => {
    const it = items.find((x) => x.id === id);
    if (it?.controller) it.controller.abort();
    setItems((prev) => prev.filter((x) => x.id !== id));
    if (it?.result) {
      onChange(value.filter((v) => v.file_id !== it.result!.file_id));
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files || []);
    handleFiles(files);
  };

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    handleFiles(files);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
        {description && (
          <span className="text-xs text-gray-500">{description}</span>
        )}
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className={[
          "border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors",
          dragging ? "border-blue-500 bg-blue-50" : "border-gray-300 hover:border-gray-400",
          disabled ? "opacity-50 cursor-not-allowed" : "",
        ].join(" ")}
        data-testid="file-upload-dropzone"
      >
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={acceptAttr}
          multiple={multiple}
          onChange={onPick}
          disabled={disabled}
        />
        <p className="text-sm text-gray-600">{placeholder}</p>
        {accept && accept.length > 0 && (
          <p className="mt-1 text-xs text-gray-400">
            支持：{accept.join(" · ")}（≤{formatSize(maxSize)}）
          </p>
        )}
      </div>

      {items.length > 0 && (
        <ul className="space-y-2" data-testid="file-upload-list">
          {items.map((it) => (
            <li
              key={it.id}
              className="flex items-center gap-3 p-3 bg-white border border-gray-200 rounded-md"
            >
              {it.file.type.startsWith("image/") && it.status === "done" && it.result ? (
                <img
                  src={it.result.url}
                  alt={it.file.name}
                  className="w-12 h-12 object-cover rounded"
                />
              ) : (
                <div className="w-12 h-12 flex items-center justify-center bg-gray-100 text-gray-500 text-xs rounded">
                  {it.file.name.split(".").pop()?.toUpperCase() || "?"}
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm text-gray-800 truncate">{it.file.name}</div>
                <div className="mt-1 flex items-center gap-2">
                  {it.status === "uploading" && (
                    <>
                      <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-blue-500 transition-all"
                          style={{ width: `${Math.round(it.progress * 100)}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-500 w-10 text-right">
                        {Math.round(it.progress * 100)}%
                      </span>
                    </>
                  )}
                  {it.status === "done" && (
                    <span className="text-xs text-green-600">
                      ✓ {formatSize(it.file.size)}
                    </span>
                  )}
                  {it.status === "error" && (
                    <span className="text-xs text-red-600">{it.error}</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1">
                {it.status === "error" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      retry(it.id);
                    }}
                  >
                    重试
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    remove(it.id);
                  }}
                >
                  {it.status === "uploading" ? "取消" : "移除"}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default FileUploadCard;
