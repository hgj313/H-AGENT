/**
 * 设计审查 - 任务配置页 - P4 + P6
 *
 * 职责：
 *  - PRD 文档：可选"文本/URL" 或 "OSS 直传文件"
 *  - 原型图：1..N 个，可"粘贴 URL" 或 "OSS 直传图片"
 *  - 补充说明 message
 *  - 触发后创建会话 + 跳转实时审查面板
 *
 * OSS 直传：I1 决策落地的 FileUploadCard 组件驱动
 *   - PRD：bucket="design-review-prd", 单文件
 *   - 原型图：bucket="design-review-image", 多文件
 *   - 完成后用 objectName 提交（业务侧与存储后端解耦）
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/common/Button";
import { Card } from "@/components/common/Card";
import { FileUploadCard } from "@/components/upload/FileUploadCard";
import { ROUTES } from "@/constants/routes";
import { designReviewService } from "@/services/designReviewService";
import type { OSSUploadResult } from "@/services/ossService";

export default function DesignReviewPage() {
  const router = useRouter();

  // PRD：文本路径 / OSS 上传
  const [prdPath, setPrdPath] = useState("");
  const [prdUploads, setPrdUploads] = useState<OSSUploadResult[]>([]);

  // 原型图：URL 列表 / OSS 上传列表
  const [imageUrlInput, setImageUrlInput] = useState("");
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [imageUploads, setImageUploads] = useState<OSSUploadResult[]>([]);

  // 补充说明
  const [message, setMessage] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addImageUrl = () => {
    const url = imageUrlInput.trim();
    if (!url) return;
    if (imageUrls.includes(url)) {
      setError("该原型图 URL 已存在");
      return;
    }
    setImageUrls((prev) => [...prev, url]);
    setImageUrlInput("");
    setError(null);
  };

  const removeImageUrl = (idx: number) => {
    setImageUrls((prev) => prev.filter((_, i) => i !== idx));
  };

  // 合并：prdPath 优先 OSS 上传，否则用文本
  const effectivePrdPath =
    prdUploads.length > 0 ? prdUploads[prdUploads.length - 1].object_name : prdPath.trim();

  // 合并：URL + OSS 全部提交
  // 注意：用 u.url（绝对 URL）而非 u.object_name（内部标识符，如 "local://..."）
  // —— 设计审查 agent 需要 fetch URL；object_name 不可被 fetch，会导致 404
  const allImageUrls = [
    ...imageUrls,
    ...imageUploads.map((u) => u.url),
  ];

  const canSubmit = !!effectivePrdPath || allImageUrls.length > 0;

  const handleStart = async () => {
    if (!canSubmit) {
      setError("请至少提供 PRD 路径/上传文件 或 1 张原型图");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const sess = await designReviewService.createSession({
        user_id: "default_user",
        prd_path: effectivePrdPath,
        image_urls: allImageUrls,
      });
      router.push(ROUTES.designReviewSession(sess.dr_session_id));
    } catch (err) {
      setError((err as Error).message ?? "创建会话失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-brand-500">设计审查</h1>
          <p className="mt-1 text-sm text-gray-500">
            配置 PRD 与原型图，触发 AI 自动审查并生成报告
          </p>
        </div>
        <Link href={ROUTES.agentHub}>
          <Button variant="ghost">返回 Agent 中心</Button>
        </Link>
      </header>

      <Card>
        <h2 className="mb-3 text-base font-medium text-brand-500">
          1. PRD 文档
        </h2>
        <p className="mb-3 text-xs text-gray-500">
          方式 A：输入本地路径 / 公网 URL；
          方式 B：直接上传文件（支持 .pdf / .docx / .md / .txt）
        </p>
        <input
          type="text"
          value={prdPath}
          onChange={(e) => setPrdPath(e.target.value)}
          placeholder="./docs/feature-prd.md  或  https://..."
          className="w-full rounded-md border border-brand-100 px-3 py-2 text-sm focus:border-brand-400 focus:outline-none"
        />
        <div className="mt-4 border-t border-gray-100 pt-4">
          <FileUploadCard
            title="上传 PRD 文件"
            description="拖拽或点击 · 单文件"
            placeholder="把 PRD 文件拖到这里（.pdf / .docx / .md / .txt）"
            accept={[".pdf", ".docx", ".md", ".txt"]}
            acceptMime={["application/pdf", "text/markdown", "text/plain"]}
            multiple={false}
            bucket="design-review-prd"
            value={prdUploads}
            onChange={setPrdUploads}
          />
        </div>
      </Card>

      <Card>
        <h2 className="mb-3 text-base font-medium text-brand-500">
          2. 原型图（1 张或以上）
        </h2>
        <p className="mb-3 text-xs text-gray-500">
          方式 A：粘贴 URL（回车添加） · 方式 B：直接拖拽上传图片
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={imageUrlInput}
            onChange={(e) => setImageUrlInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addImageUrl();
              }
            }}
            placeholder="https://...  粘贴后回车添加"
            className="flex-1 rounded-md border border-brand-100 px-3 py-2 text-sm focus:border-brand-400 focus:outline-none"
          />
          <Button variant="secondary" onClick={addImageUrl} type="button">
            添加
          </Button>
        </div>
        {imageUrls.length > 0 && (
          <ul className="mt-3 space-y-2">
            {imageUrls.map((url, i) => (
              <li
                key={url}
                className="flex items-center gap-2 rounded-md border border-brand-50 bg-brand-50/50 px-3 py-2 text-xs"
              >
                <span className="flex-1 truncate text-gray-600" title={url}>
                  {i + 1}. {url}
                </span>
                <button
                  type="button"
                  onClick={() => removeImageUrl(i)}
                  className="text-red-500 hover:text-red-600"
                  aria-label="移除"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-4 border-t border-gray-100 pt-4">
          <FileUploadCard
            title="上传原型图"
            description="拖拽或点击 · 多文件"
            placeholder="把原型图拖到这里（.png / .jpg / .jpeg / .webp）"
            accept={[".png", ".jpg", ".jpeg", ".webp"]}
            acceptMime={["image/png", "image/jpeg", "image/webp"]}
            multiple
            bucket="design-review-image"
            value={imageUploads}
            onChange={setImageUploads}
          />
        </div>
      </Card>

      <Card>
        <h2 className="mb-3 text-base font-medium text-brand-500">
          3. 补充说明（可选）
        </h2>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={3}
          placeholder="本次审查的重点、注意事项、特殊规范等..."
          className="w-full rounded-md border border-brand-100 px-3 py-2 text-sm focus:border-brand-400 focus:outline-none"
        />
      </Card>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Link href={ROUTES.agentHub}>
          <Button variant="ghost" type="button">
            取消
          </Button>
        </Link>
        <Button onClick={handleStart} disabled={!canSubmit} loading={submitting}>
          开始审查
        </Button>
      </div>
    </div>
  );
}
