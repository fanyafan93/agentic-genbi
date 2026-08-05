import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import { listSystemMcpServers } from "@/modules/system/server/system-backend-client";
import { systemRouteError } from "@/modules/system/server/system-route-response";

type RouteContext = { params: Promise<{ serverName: string }> };

export async function PATCH(request: Request, context: RouteContext) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const body = (await request.json()) as Record<string, unknown>;
  if (typeof body.enabled !== "boolean") {
    return NextResponse.json({ error: "invalid_mcp_update" }, { status: 422 });
  }
  const { serverName } = await context.params;
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    const configured = await listSystemMcpServers();
    if (!configured.some((server) => server.name === serverName)) {
      return NextResponse.json({ error: "mcp_server_not_found" }, { status: 404 });
    }
    await prisma.$transaction([
      prisma.systemSetting.upsert({
        where: { key: `mcp.enabled.${serverName}` },
        create: {
          key: `mcp.enabled.${serverName}`,
          value: { enabled: body.enabled },
          updatedById: session.user.id,
        },
        update: {
          value: { enabled: body.enabled },
          updatedById: session.user.id,
        },
      }),
      prisma.systemAuditLog.create({
        data: {
          actorId: session.user.id,
          action: body.enabled ? "mcp.enable" : "mcp.disable",
          targetType: "mcp_server",
          targetId: serverName,
          after: { enabled: body.enabled },
        },
      }),
    ]);
    return NextResponse.json({ name: serverName, enabled: body.enabled });
  } catch (error) {
    return systemRouteError(error);
  }
}
