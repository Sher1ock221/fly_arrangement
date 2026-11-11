"use client";
import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface UserOption {
  id: number;
  username: string;
  display_name: string | null;
  is_active?: boolean;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onConfirm: (targetUserId: number) => Promise<void>;
  allUsers: UserOption[];
  currentOwnerUserId?: number;
  resourceLabel: string;
}

export default function TransferOwnerDialog({
  open, onClose, onConfirm, allUsers, currentOwnerUserId, resourceLabel,
}: Props) {
  const [selectedUserId, setSelectedUserId] = useState<number | "">("");
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<"select" | "confirm">("select");

  const eligibleUsers = allUsers.filter(
    (u) => u.id !== currentOwnerUserId && u.is_active !== false,
  );

  const selectedUser = eligibleUsers.find((u) => u.id === selectedUserId);

  const handleNext = () => {
    if (!selectedUserId) return;
    setStep("confirm");
  };

  const handleConfirm = async () => {
    if (!selectedUserId) return;
    setBusy(true);
    try {
      await onConfirm(Number(selectedUserId));
      setStep("select");
      setSelectedUserId("");
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const handleClose = () => {
    setStep("select");
    setSelectedUserId("");
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle>转移{resourceLabel}负责人</DialogTitle>
        </DialogHeader>

        {step === "select" ? (
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              请选择新的负责人（当前负责人不会出现在列表中）。转移后，对方将成为新的负责人，你将自动保留为协作者。
            </p>
            {eligibleUsers.length > 0 ? (
              <select
                value={selectedUserId}
                onChange={(e) => setSelectedUserId(e.target.value ? Number(e.target.value) : "")}
                className="w-full text-sm border border-border rounded-md px-3 py-2 bg-background focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">选择用户…</option>
                {eligibleUsers.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.display_name || u.username}
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-sm text-muted-foreground py-4 text-center">暂无可转移目标用户</p>
            )}
          </div>
        ) : (
          <div className="space-y-3 py-2">
            <p className="text-sm font-medium text-orange-700 bg-orange-50 border border-orange-200 rounded-md p-3">
              确定要将该{resourceLabel}的负责人转移给
              <strong>「{selectedUser?.display_name || selectedUser?.username}」</strong>吗？
            </p>
            <ul className="text-sm text-muted-foreground space-y-1 pl-4 list-disc">
              <li>{selectedUser?.display_name || selectedUser?.username} 将成为新的负责人</li>
              <li>你将自动保留为协作者</li>
              <li>此操作不可自动撤销</li>
            </ul>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={busy}>
            取消
          </Button>
          {step === "select" ? (
            <Button onClick={handleNext} disabled={!selectedUserId || eligibleUsers.length === 0}>
              下一步
            </Button>
          ) : (
            <Button variant="destructive" onClick={handleConfirm} disabled={busy}>
              {busy ? "转移中…" : "确认转移"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
