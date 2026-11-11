"use client";

import { useAuth } from "@/contexts/AuthContext";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function HelpPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle>使用说明</CardTitle>
          <CardDescription>普通用户与管理员均可查看（桌面单机版）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6 text-sm">
          <section>
            <h3 className="font-medium mb-2">普通用户</h3>
            <ul className="list-disc pl-4 space-y-1 text-muted-foreground">
              <li>登录后可在「个人设置」中修改显示名、密码。</li>
              <li>项目管理、客户管理、日历、本地提醒与 AI 助手中的数据按当前登录用户隔离。</li>
              <li>AI 助手依赖本机 Ollama：请在「模型配置」中填写正确的服务地址与模型名，并可使用「测试连接」自检。</li>
            </ul>
          </section>
          {isAdmin && (
            <section>
              <h3 className="font-medium mb-2">管理员</h3>
              <ul className="list-disc pl-4 space-y-1 text-muted-foreground">
                <li>「管理员概览」可查看用户数与最近审计日志等汇总信息。</li>
                <li>「账号管理」可创建/编辑/禁用用户、重置密码。</li>
                <li>「审计日志」可按动作、资源类型、日期筛选，并支持导出 CSV。</li>
                <li>「系统状态」可查看数据库与模型配置等运行状态。</li>
                <li>「系统信息」可查看版本与功能说明。</li>
              </ul>
            </section>
          )}
          <section>
            <h3 className="font-medium mb-2">关于外部协作</h3>
            <p className="text-muted-foreground">
              本桌面安装包不包含飞书 Webhook、身份池或云端同步；数据默认保存在本机 SQLite。若你需要服务端飞书集成，请使用完整服务端部署渠道。
            </p>
          </section>
          <section>
            <h3 className="font-medium mb-2">常见问题</h3>
            <ul className="list-disc pl-4 space-y-1 text-muted-foreground">
              <li>忘记密码：请联系管理员在「账号管理」中为你重置密码。</li>
              <li>首次登录提示修改密码：请在「个人设置」-「修改密码」中完成修改。</li>
              <li>AI 无响应或很慢：请确认 Ollama 已启动、模型已拉取，并适当缩短单次对话复杂度。</li>
            </ul>
          </section>
        </CardContent>
      </Card>
    </div>
  );
}
