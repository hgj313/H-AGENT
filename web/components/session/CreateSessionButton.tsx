"use client";

import { useRouter } from "next/navigation";
import { useCreateSession } from "@/hooks/useCreateSession";
import { Button } from "@/components/common/Button";
import { ROUTES } from "@/constants/routes";

export interface CreateSessionButtonProps {
  userId?: string;
  agentId?: string;
  /** 创建后是否跳转 */
  navigateOnSuccess?: boolean;
  label?: string;
}

/** 新建会话按钮 - mutation + 自动选中 + 可选跳转 */
export function CreateSessionButton({
  userId,
  agentId,
  navigateOnSuccess = true,
  label = "+ 新建会话",
}: CreateSessionButtonProps) {
  const router = useRouter();
  const create = useCreateSession();

  return (
    <Button
      variant="primary"
      loading={create.isPending}
      onClick={async () => {
        const sess = await create.mutateAsync({ userId, agentId });
        if (navigateOnSuccess) {
          router.push(ROUTES.chatSession(sess.session_id));
        }
      }}
      aria-label="新建会话"
    >
      {label}
    </Button>
  );
}
