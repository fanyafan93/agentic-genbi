import { PrismaAdapter } from "@auth/prisma-adapter";
import NextAuth, { type NextAuthConfig } from "next-auth";
import type { OAuthConfig } from "next-auth/providers";

import { prisma } from "@/lib/prisma";
import { mapFeishuProfile, type FeishuProfile } from "@/modules/auth/feishu-profile";

type FeishuTokenPayload = {
  code?: number;
  msg?: string;
  data?: {
    access_token?: string;
    refresh_token?: string;
    expires_in?: number;
    token_type?: string;
    scope?: string;
  };
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  token_type?: string;
  scope?: string;
};

type FeishuUserPayload = {
  code?: number;
  msg?: string;
  data?: FeishuProfile;
} & FeishuProfile;

type FeishuTokenRequestContext = {
  provider: {
    clientId?: string;
    clientSecret?: string;
    callbackUrl?: string;
  };
  params: {
    code?: string;
  };
};

type FeishuUserInfoRequestContext = {
  tokens: {
    access_token?: string;
  };
};

function feishuProvider(): OAuthConfig<FeishuProfile> {
  return {
    id: "feishu",
    name: "飞书",
    type: "oauth",
    checks: ["state"],
    clientId: process.env.FEISHU_APP_ID,
    clientSecret: process.env.FEISHU_APP_SECRET,
    authorization: {
      url: "https://accounts.feishu.cn/open-apis/authen/v1/authorize?scope=",
    },
    token: {
      url: "https://open.feishu.cn/open-apis/authen/v2/oauth/token",
      async request(context: FeishuTokenRequestContext) {
        const response = await fetch("https://open.feishu.cn/open-apis/authen/v2/oauth/token", {
          method: "POST",
          headers: { "Content-Type": "application/json; charset=utf-8" },
          body: JSON.stringify({
            grant_type: "authorization_code",
            client_id: context.provider.clientId,
            client_secret: context.provider.clientSecret,
            code: context.params.code,
            redirect_uri: context.provider.callbackUrl,
          }),
        });
        const payload = (await response.json()) as FeishuTokenPayload;
        const data = payload.data ?? payload;
        if (!response.ok || !data.access_token) {
          throw new Error(payload.msg || "feishu_oauth_token_failed");
        }
        return {
          tokens: {
            access_token: data.access_token,
            refresh_token: data.refresh_token,
            token_type: data.token_type ?? "Bearer",
            scope: data.scope,
            expires_at: data.expires_in ? Math.floor(Date.now() / 1000) + data.expires_in : undefined,
          },
        };
      },
    },
    userinfo: {
      url: "https://open.feishu.cn/open-apis/authen/v1/user_info",
      async request({ tokens }: FeishuUserInfoRequestContext) {
        const response = await fetch("https://open.feishu.cn/open-apis/authen/v1/user_info", {
          headers: { Authorization: `Bearer ${tokens.access_token}` },
        });
        const payload = (await response.json()) as FeishuUserPayload;
        const profile = payload.data ?? payload;
        if (!response.ok || !(profile.open_id || profile.union_id || profile.user_id)) {
          throw new Error(payload.msg || "feishu_userinfo_failed");
        }
        return profile;
      },
    },
    profile(profile) {
      return mapFeishuProfile(profile);
    },
  };
}

export const authConfig = {
  adapter: PrismaAdapter(prisma),
  session: { strategy: "database" },
  providers: [feishuProvider()],
  trustHost: true,
  callbacks: {
    signIn({ user }) {
      return user.status !== "disabled";
    },
    session({ session, user }) {
      if (session.user) {
        session.user.id = user.id;
        session.user.role = user.role;
        session.user.status = user.status;
      }
      return session;
    },
  },
  pages: {
    signIn: "/",
  },
} satisfies NextAuthConfig;

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);
