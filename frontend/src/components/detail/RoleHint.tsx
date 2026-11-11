"use client";

interface RoleHintProps {
  accessRole: "owner" | "collaborator";
}

export default function RoleHint({ accessRole }: RoleHintProps) {
  if (accessRole === "owner") return null;

  return (
    <div className="rounded-lg bg-amber-50 border border-amber-200/60 px-4 py-2.5 text-xs text-amber-800">
      你当前以协作者身份参与，可查看并补充协作内容，但不能修改核心信息或管理共享成员
    </div>
  );
}
