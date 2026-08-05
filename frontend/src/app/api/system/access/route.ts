import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { PrismaSystemUserRepository } from "@/modules/system/server/prisma-system-user-repository";
import { resolveSystemAccess } from "@/modules/system/server/system-user-management";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ access: "unauthenticated" }, { status: 401 });
  }
  const repository = new PrismaSystemUserRepository(prisma);
  const actor = await repository.get(session.user.id);
  if (!actor) {
    return NextResponse.json({ access: "unauthenticated" }, { status: 401 });
  }
  const access = resolveSystemAccess(
    actor,
    await repository.countActiveAdministrators(),
  );
  return NextResponse.json({ access });
}
