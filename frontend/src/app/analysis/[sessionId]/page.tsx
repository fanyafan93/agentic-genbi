import { auth } from "@/auth";
import { AnalysisWorkspace } from "@/modules/analysis/components/AnalysisWorkspace";
import { SignInScreen } from "@/modules/auth/components/SignInScreen";

type AnalysisSessionPageProps = {
  params: Promise<{ sessionId: string }>;
};

export default async function AnalysisSessionPage({ params }: AnalysisSessionPageProps) {
  const session = await auth();
  if (!session?.user || session.user.status === "disabled") return <SignInScreen />;

  const { sessionId } = await params;
  return <AnalysisWorkspace initialSessionId={sessionId} />;
}
