import { FineReportReportBrowser } from "./FineReportReportBrowser";

export type BusinessSemanticSection = "structured" | "semantic";
export type StructuredKnowledgeSource = "finereport" | "hop" | "database" | "kingdee";

export function BusinessSemanticLibrary({
  section = "structured",
  structuredKnowledgeSource = "finereport",
}: {
  section?: BusinessSemanticSection;
  structuredKnowledgeSource?: StructuredKnowledgeSource;
}) {
  return (
    <section
      className="business-semantic-page business-semantic-page-empty"
      aria-label="业务语义库"
    >
      {section === "structured" && structuredKnowledgeSource === "finereport" ? <FineReportReportBrowser /> : null}
    </section>
  );
}
