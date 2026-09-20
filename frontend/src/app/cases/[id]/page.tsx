import { CaseDetail } from "@/components/CaseDetail";

export default function CasePage({ params }: { params: { id: string } }) {
  return <CaseDetail id={params.id} />;
}
