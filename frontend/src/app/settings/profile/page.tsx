"use client";

import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authApi } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle, Loader2, User, Key } from "lucide-react";
import { toast } from "sonner";

export default function ProfilePage() {
  const { user, refetch } = useAuth();
  const [displayName, setDisplayName] = useState("");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [loadingPassword, setLoadingPassword] = useState(false);

  useEffect(() => {
    if (user) setDisplayName(user.display_name || "");
  }, [user]);

  const handleSaveProfile = async () => {
    setLoadingProfile(true);
    try {
      await authApi.updateMe({ display_name: displayName.trim() || null });
      toast.success("资料已更新");
      refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingProfile(false);
    }
  };

  const handleChangePassword = async () => {
    if (newPassword !== confirmPassword) {
      toast.error("两次输入的新密码不一致");
      return;
    }
    if (newPassword.length < 6) {
      toast.error("新密码至少 6 位");
      return;
    }
    setLoadingPassword(true);
    try {
      await authApi.changePassword({ old_password: oldPassword, new_password: newPassword });
      toast.success("密码已修改");
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
      refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingPassword(false);
    }
  };

  if (!user) return null;

  return (
    <div className="space-y-6 max-w-2xl">
      {user.must_change_password && (
        <Alert variant="destructive" className="border-amber-500 bg-amber-50 dark:bg-amber-950/30">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            你当前需要修改密码后再继续安全使用系统。请在下方「修改密码」中完成修改。
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <User className="h-5 w-5" />
            基础资料
          </CardTitle>
          <CardDescription>用户名不可修改；显示名将用于界面展示</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2">
            <Label>用户名</Label>
            <Input value={user.username} readOnly disabled className="bg-muted" />
          </div>
          <div className="grid gap-2">
            <Label>显示名</Label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="选填"
              maxLength={128}
            />
          </div>
          <div className="grid gap-2">
            <Label>角色</Label>
            <Input
              value={user.role === "admin" ? "管理员" : "普通用户"}
              readOnly
              disabled
              className="bg-muted"
            />
          </div>
          {user.last_login_at && (
            <div className="grid gap-2">
              <Label>最近登录</Label>
              <Input
                value={new Date(user.last_login_at).toLocaleString("zh-CN")}
                readOnly
                disabled
                className="bg-muted"
              />
            </div>
          )}
          {user.created_at && (
            <div className="grid gap-2">
              <Label>注册时间</Label>
              <Input
                value={new Date(user.created_at).toLocaleString("zh-CN")}
                readOnly
                disabled
                className="bg-muted"
              />
            </div>
          )}
          <Button onClick={handleSaveProfile} disabled={loadingProfile}>
            {loadingProfile ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            保存资料
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Key className="h-5 w-5" />
            修改密码
          </CardTitle>
          <CardDescription>修改后请使用新密码登录</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2">
            <Label>当前密码</Label>
            <Input
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              placeholder="请输入当前密码"
              autoComplete="current-password"
            />
          </div>
          <div className="grid gap-2">
            <Label>新密码</Label>
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="至少 6 位"
              autoComplete="new-password"
            />
          </div>
          <div className="grid gap-2">
            <Label>确认新密码</Label>
            <Input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="再次输入新密码"
              autoComplete="new-password"
            />
          </div>
          <Button onClick={handleChangePassword} disabled={loadingPassword} variant="secondary">
            {loadingPassword ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            修改密码
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>飞书身份</CardTitle>
          <CardDescription>桌面版已停用飞书绑定展示</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground leading-relaxed">
            个人设置页不再请求飞书绑定接口。账号与密码仍可在上方卡片中维护。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
