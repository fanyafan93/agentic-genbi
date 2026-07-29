export type ArtifactKind = "html" | "sql" | "python" | "csv" | "markdown" | "json";

export type ArtifactFile = { id: string; name: string; kind: ArtifactKind };

export type ArtifactFolder = { id: string; name: string; children: ArtifactFile[] };
