import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import {
  listSystemMcpServers,
  listSystemSkills,
  getSystemRuntimeStatus,
} from "@/modules/system/server/system-backend-client";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import { systemRouteError } from "@/modules/system/server/system-route-response";
import {
  SystemContextSettingsError,
  validateSystemContextUpdate,
} from "@/modules/system/system-context-settings";

const BASE_INSTRUCTIONS_KEY = "context.base_instructions";
const SYSTEM_PROMPT_KEY = "context.system_prompt";

function instructionContent(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const content = (value as { content?: unknown }).content;
  return typeof content === "string" ? content.trim() : "";
}

async function managedContext() {
  const [settings, publishedPrompt, runtime, skills, mcpServers] =
    await Promise.all([
      prisma.systemSetting.findMany({
        where: { key: { in: [BASE_INSTRUCTIONS_KEY, SYSTEM_PROMPT_KEY] } },
      }),
      prisma.systemPromptVersion.findFirst({
        where: { promptKey: "analysis_system", status: "published" },
        orderBy: { version: "desc" },
      }),
      getSystemRuntimeStatus(),
      listSystemSkills(),
      listSystemMcpServers(),
    ]);
  const byKey = new Map(settings.map((setting) => [setting.key, setting]));
  const baseSetting = byKey.get(BASE_INSTRUCTIONS_KEY);
  const systemSetting = byKey.get(SYSTEM_PROMPT_KEY);
  const baseContent = instructionContent(baseSetting?.value);
  const systemContent =
    instructionContent(systemSetting?.value) || publishedPrompt?.content.trim() || "";

  return {
    baseInstructions: {
      content: baseContent,
      source: baseContent ? ("managed" as const) : ("codex_native" as const),
      updatedAt: baseSetting?.updatedAt.toISOString() ?? null,
    },
    systemPrompt: {
      content: systemContent,
      updatedAt:
        systemSetting?.updatedAt.toISOString()
        ?? publishedPrompt?.publishedAt?.toISOString()
        ?? null,
    },
    runtime,
    skills,
    mcpServers,
  };
}

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    return NextResponse.json({ context: await managedContext() });
  } catch (error) {
    return systemRouteError(error);
  }
}

export async function PUT(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    const update = validateSystemContextUpdate(
      (await request.json()) as Record<string, unknown>,
    );
    const [key, content] =
      "baseInstructions" in update
        ? [BASE_INSTRUCTIONS_KEY, update.baseInstructions]
        : [SYSTEM_PROMPT_KEY, update.systemPrompt];
    await prisma.systemSetting.upsert({
      where: { key },
      create: {
        key,
        value: { content },
        updatedById: session.user.id,
      },
      update: {
        value: { content },
        updatedById: session.user.id,
      },
    });
    return NextResponse.json({ context: await managedContext() });
  } catch (error) {
    if (error instanceof SystemContextSettingsError) {
      return NextResponse.json({ error: error.code }, { status: 422 });
    }
    return systemRouteError(error);
  }
}
