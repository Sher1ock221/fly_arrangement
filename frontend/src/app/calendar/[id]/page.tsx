"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Calendar, Briefcase, ArrowRightLeft, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  calendarApi,
  calendarCollabApi,
  projectsApi,
} from "@/lib/apiClient";
import { useAuth } from "@/contexts/AuthContext";
import { queryKeys } from "@/lib/queryKeys";
import { Button } from "@/components/ui/button";
import DetailHeader from "@/components/detail/DetailHeader";
import InfoGrid from "@/components/detail/InfoGrid";
import RelatedResourceList from "@/components/detail/RelatedResourceList";
import RoleHint from "@/components/detail/RoleHint";
import DetailSkeleton from "@/components/detail/DetailSkeleton";
import DetailError from "@/components/detail/DetailError";
import CollaboratorPanel from "@/components/collaboration/CollaboratorPanel";
import ActivityFeed from "@/components/collaboration/ActivityFeed";
import TransferOwnerDialog from "@/components/collaboration/TransferOwnerDialog";
import { formatLocalDateTime } from "@/lib/time";

const TYPE_LABEL: Record<string, string> = {
  event: "日程",
  project: "项目",
  meeting: "会议",
  task: "任务",
};

function formatDateTime(s: string | null | undefined): string {
  return formatLocalDateTime(s);
}

export default function CalendarEventDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = typeof params.id === "string" ? parseInt(params.id, 10) : NaN;
  const qc = useQueryClient();
  const [transferOpen, setTransferOpen] = useState(false);
  const { user } = useAuth();

  /* ---- data queries (ALL hooks before any returns) ---- */

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.calendarEventDetail(id),
    queryFn: () => calendarApi.getEvent(id),
    enabled: Number.isInteger(id),
  });

  const isOwner = data
    ? data.access_role === "owner" || !data.access_role
    : false;

  const { data: project } = useQuery({
    queryKey: queryKeys.projectDetail(data?.project_id ?? 0),
    queryFn: () => projectsApi.get(data!.project_id!),
    enabled: !!data?.project_id,
  });

  const { data: collaborators = [], isLoading: collabLoading } = useQuery({
    queryKey: queryKeys.calendarEventCollaborators(id),
    queryFn: () => calendarCollabApi.listCollaborators(id),
    enabled: Number.isInteger(id),
  });

  const { data: comments = [], isLoading: commentsLoading } = useQuery({
    queryKey: queryKeys.calendarEventComments(id),
    queryFn: () => calendarCollabApi.listComments(id),
    enabled: Number.isInteger(id),
  });

  const { data: usersData } = useQuery({
    queryKey: queryKeys.projectSelectableUsers(),
    queryFn: () => projectsApi.listSelectableUsers(),
    enabled: isOwner,
  });

  /* ---- conditional returns ---- */

  if (isLoading) {
    return <DetailSkeleton backHref="/calendar" backLabel="返回日程" />;
  }

  if (error || !data) {
    return (
      <DetailError
        backHref="/calendar"
        backLabel="返回日程"
        message={error instanceof Error ? error.message : undefined}
      />
    );
  }

  const event = data;

  const handleDelete = async () => {
    if (!confirm("确定要删除该日程吗？")) return;
    try {
      await calendarApi.deleteEvent(id);
      qc.invalidateQueries({ queryKey: queryKeys.calendarEvents() });
      toast.success("日程已删除");
      router.push("/calendar");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const projectItems = project
    ? [
        {
          id: project.id,
          href: `/projects/${project.id}`,
          title: project.name,
          subtitle: project.project_no,
          badge: project.owner,
        },
      ]
    : [];

  return (
    <div className="flex flex-col h-full">
      <DetailHeader
        backHref="/calendar"
        backLabel="返回日程"
        title={event.title}
        subtitle={TYPE_LABEL[event.type] || event.type}
        accessRole={event.access_role}
        actions={
          isOwner ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTransferOpen(true)}
                className="gap-1.5 text-xs"
              >
                <ArrowRightLeft className="h-3.5 w-3.5" />
                转移负责人
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleDelete}
                className="gap-1.5 text-xs text-destructive hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除
              </Button>
            </>
          ) : undefined
        }
      />

      <div className="flex-1 overflow-auto p-4 md:p-6 space-y-5">
        {event.access_role === "collaborator" && (
          <RoleHint accessRole="collaborator" />
        )}

        <InfoGrid
          title="日程信息"
          icon={<Calendar className="h-4 w-4" />}
          fields={[
            { label: "日程标题", value: event.title },
            {
              label: "类型",
              value: TYPE_LABEL[event.type] || event.type,
            },
            { label: "开始时间", value: formatDateTime(event.start_time) },
            { label: "结束时间", value: formatDateTime(event.end_time) },
            { label: "描述", value: event.description, span: 2 },
            { label: "更新时间", value: formatDateTime(event.updated_at) },
          ]}
        />

        <RelatedResourceList
          title="关联项目"
          icon={<Briefcase className="h-4 w-4" />}
          items={projectItems}
          emptyText="暂无关联项目"
        />

        <CollaboratorPanel
          collaborators={collaborators}
          isOwner={isOwner}
          ownerUserId={event.owner_user_id ?? undefined}
          ownerDisplayName={(usersData || []).find((u) => u.id === event.owner_user_id)?.display_name || undefined}
          allUsers={usersData || []}
          onAdd={async (userId) => {
            await calendarCollabApi.addCollaborator(id, { user_id: userId });
            qc.invalidateQueries({
              queryKey: queryKeys.calendarEventCollaborators(id),
            });
          }}
          onRemove={async (userId) => {
            await calendarCollabApi.removeCollaborator(id, userId);
            qc.invalidateQueries({
              queryKey: queryKeys.calendarEventCollaborators(id),
            });
          }}
          loading={collabLoading}
        />

        <ActivityFeed
          title="评论记录"
          subtitle="补充说明、准备事项或会议备注"
          items={comments}
          canAdd={true}
          placeholder="补充说明、准备事项或会议备注…"
          onAdd={async (content) => {
            await calendarCollabApi.addComment(id, { content });
            qc.invalidateQueries({ queryKey: queryKeys.calendarEventComments(id) });
          }}
          onDelete={async (commentId) => {
            await calendarCollabApi.deleteComment(id, commentId);
            qc.invalidateQueries({ queryKey: queryKeys.calendarEventComments(id) });
          }}
          currentUserId={user?.id ?? null}
          isResourceOwner={isOwner}
          loading={commentsLoading}
        />
      </div>

      <TransferOwnerDialog
        open={transferOpen}
        onClose={() => setTransferOpen(false)}
        onConfirm={async (targetUserId) => {
          await calendarCollabApi.transferOwner(id, {
            target_user_id: targetUserId,
          });
          toast.success("日程负责人已转移");
          qc.invalidateQueries({ queryKey: queryKeys.calendarEventDetail(id) });
          qc.invalidateQueries({ queryKey: queryKeys.calendarEventCollaborators(id) });
        }}
        allUsers={usersData || []}
        currentOwnerUserId={event.owner_user_id ?? undefined}
        resourceLabel="日程"
      />
    </div>
  );
}
