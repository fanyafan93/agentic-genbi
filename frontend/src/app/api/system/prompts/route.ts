import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { PrismaSystemPromptRepository } from "@/modules/system/server/prisma-system-prompt-repository";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import { SystemPromptManagementService } from "@/modules/system/server/system-prompt-management";
import { systemRouteError } from "@/modules/system/server/system-route-response";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    const prompts = await new SystemPromptManagementService(
      new PrismaSystemPromptRepository(prisma),
    ).list();
    return NextResponse.json({ prompts });
  } catch (error) {
    return systemRouteError(error);
  }
}

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const body = (await request.json()) as Record<string, unknown>;
  try {
    const prompt = await prisma.$transaction(async (transaction) => {
      await transaction.$executeRaw`SELECT pg_advisory_xact_lock(hashtext('genbi_system_prompt_management'))`;
      await requireSystemAdministrator(session.user.id, transaction);
      const created = await new SystemPromptManagementService(
        new PrismaSystemPromptRepository(transaction),
      ).createDraft(session.user.id, {
        promptKey: String(body.promptKey || ""),
        name: String(body.name || ""),
        description:
          typeof body.description === "string" ? body.description : null,
        content: String(body.content || ""),
      });
      await transaction.systemAuditLog.create({
        data: {
          actorId: session.user.id,
          action: "prompt.draft.create",
          targetType: "system_prompt",
          targetId: created.id,
          after: {
            promptKey: created.promptKey,
            version: created.version,
            status: created.status,
          },
        },
      });
      return created;
    });
    return NextResponse.json({ prompt }, { status: 201 });
  } catch (error) {
    return systemRouteError(error);
  }
}
