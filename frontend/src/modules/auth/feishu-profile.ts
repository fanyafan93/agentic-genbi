export type FeishuProfile = {
  open_id?: string;
  union_id?: string;
  user_id?: string;
  name?: string;
  en_name?: string;
  email?: string;
  avatar_url?: string;
  avatar_thumb?: string;
};

export function mapFeishuProfile(profile: FeishuProfile) {
  const id = profile.union_id || profile.open_id || profile.user_id;
  if (!id) {
    throw new Error("feishu_profile_missing_id");
  }
  return {
    id,
    name: profile.name || profile.en_name || "飞书用户",
    email: profile.email || null,
    image: profile.avatar_url || profile.avatar_thumb || null,
    role: "user",
  };
}
