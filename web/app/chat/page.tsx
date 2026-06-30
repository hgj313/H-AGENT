/**
 * 通用对话 - 未选中会话视图
 */
import Link from "next/link";
import { Button } from "@/components/common/Button";
import { ROUTES } from "@/constants/routes";

export default function ChatPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-gray-500">
      <p className="text-sm">请在左侧选择或新建一个会话</p>
      <p className="text-xs text-gray-400">
        也可以
        <Link href={ROUTES.agentHub} className="ml-1 text-brand-500 underline">
          返回 Agent 中心
        </Link>
      </p>
    </div>
  );
}
