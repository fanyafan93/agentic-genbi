import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import { revealSystemModelConnectionSecret } from "@/modules/system/server/system-backend-client";
import { systemRouteError } from "@/modules/system/server/system-route-response";

type RouteContext = { params: Promise<{ connectionName: string }> };

export async function GET(_: Request, context: RouteContext) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const { connectionName } = await context.params;
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    const apiKey = await revealSystemModelConnectionSecret(connectionName);
    return NextResponse.json(
      { apiKey },
      {
        headers: {
          "Cache-Control": "no-store",
          Pragma: "no-cache",
        },
      },
    );
  } catch (error) {
    return systemRouteError(error);
  }
}
