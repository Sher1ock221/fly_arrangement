"use client";



import {

  createContext,

  useCallback,

  useContext,

  useEffect,

  useState,

  type ReactNode,

} from "react";

import {

  authApi,

  getStoredToken,

  setStoredToken,

  setUnauthorizedHandler,

  type UserInfo,

} from "@/lib/apiClient";



type AuthContextValue = {

  user: UserInfo | null;

  token: string | null;

  loading: boolean;

  isAuthenticated: boolean;

  login: (username: string, password: string) => Promise<UserInfo | null>;

  logout: () => void;

  refetch: () => Promise<void>;

};



const AuthContext = createContext<AuthContextValue | null>(null);



export function AuthProvider({ children }: { children: ReactNode }) {

  const [user, setUser] = useState<UserInfo | null>(null);

  const [token, setToken] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);



  const refetch = useCallback(async () => {

    const t = getStoredToken();

    setToken(t);

    if (!t) {

      setUser(null);

      setLoading(false);

      return;

    }

    try {

      const u = await authApi.me(t);

      setUser(u);

    } catch {

      setStoredToken(null);

      setToken(null);

      setUser(null);

    } finally {

      setLoading(false);

    }

  }, []);



  useEffect(() => {

    refetch();

  }, [refetch]);



  useEffect(() => {

    setUnauthorizedHandler(() => {

      setStoredToken(null);

      setToken(null);

      setUser(null);

      if (typeof window !== "undefined") window.location.replace("/login?expired=1");

    });

    return () => setUnauthorizedHandler(null);

  }, []);



  const login = useCallback(async (username: string, password: string): Promise<UserInfo | null> => {

    const res = await authApi.login({ username, password });

    setStoredToken(res.access_token);

    setToken(res.access_token);

    setUser(res.user);

    return res.user;

  }, []);



  const logout = useCallback(() => {

    setStoredToken(null);

    setToken(null);

    setUser(null);

  }, []);



  return (

    <AuthContext.Provider

      value={{

        user,

        token,

        loading,

        isAuthenticated: !loading && !!user,

        login,

        logout,

        refetch,

      }}

    >

      {children}

    </AuthContext.Provider>

  );

}



export function useAuth(): AuthContextValue {

  const ctx = useContext(AuthContext);

  if (!ctx) throw new Error("useAuth must be used within AuthProvider");

  return ctx;

}
