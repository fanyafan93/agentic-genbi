import { auth } from "@/auth";
import { AnalysisWorkspace } from "@/modules/analysis/components/AnalysisWorkspace";
import { SignInScreen } from "@/modules/auth/components/SignInScreen";

export default async function HomePage() {
  const session = await auth();
  if (!session?.user || session.user.status === "disabled") return <SignInScreen />;
  return <AnalysisWorkspace />;
}
